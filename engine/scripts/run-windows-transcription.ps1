param(
    [Parameter(Mandatory = $true)]
    [string]$ProjectDir,

    [Parameter(Mandatory = $true)]
    [string]$Source,

    [string]$Model = "large-v3",
    [string]$Device = "cuda",
    [string]$ComputeType = "int8_float16",
    [string]$Language = "ko",

    [ValidateRange(60, 3600)]
    [int]$ChunkSeconds = 600,

    [switch]$CpuFallback,
    [switch]$Resume
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$VeaExe = Join-Path $RepoRoot ".venv-windows\Scripts\vea.exe"
$ProjectFull = (Resolve-Path -LiteralPath $ProjectDir).Path
$SourceFull = (Resolve-Path -LiteralPath $Source).Path
$ProjectJsonPath = Join-Path $ProjectFull "project.json"
$SelectionPath = Join-Path $ProjectFull "03_ANALYSIS\voice_selection.json"
$TracksPath = Join-Path $ProjectFull "03_ANALYSIS\tracks.json"
$VoiceTracksPath = Join-Path $ProjectFull "05_AUDIO\voice_tracks.json"
$VoiceWavPath = Join-Path $ProjectFull "05_AUDIO\roughcut_voice.wav"
$TranscriptsDir = Join-Path $ProjectFull "07_TRANSCRIPTS"
$TranscriptSrtPath = Join-Path $TranscriptsDir "transcript.srt"
$BeforeReviewSrtPath = Join-Path $TranscriptsDir "transcript_before_review.srt"
$AfterAiReviewSrtPath = Join-Path $TranscriptsDir "transcript_after_ai_review.srt"
$RunSettingsPath = Join-Path $TranscriptsDir "windows_transcription_run.json"
$LogPath = Join-Path $env:TEMP ("vea-transcription-{0}.log" -f (Get-Date -Format "yyyyMMdd-HHmmss"))
$CudaWheelBinPaths = @(
    (Join-Path $RepoRoot ".venv-windows\Lib\site-packages\nvidia\cublas\bin"),
    (Join-Path $RepoRoot ".venv-windows\Lib\site-packages\nvidia\cuda_runtime\bin")
)
$CudaWheelBinPaths = @($CudaWheelBinPaths | Where-Object { Test-Path -LiteralPath $_ -PathType Container })
if ($CudaWheelBinPaths.Count -gt 0) {
    # Process-local only: make NVIDIA's venv-installed CUDA DLLs visible to
    # CTranslate2's Windows dynamic loader without changing machine PATH.
    $env:PATH = ($CudaWheelBinPaths -join ";") + ";" + $env:PATH
}

function Write-RunLog {
    param([Parameter(Mandatory = $true)][string]$Message)
    $Line = "[{0}] {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Message
    $Line | Tee-Object -FilePath $LogPath -Append
}

function Invoke-Vea {
    param(
        [Parameter(Mandatory = $true)][string[]]$VeaArguments,
        [int[]]$AcceptedExitCodes = @(0)
    )
    Write-RunLog ("vea " + ($VeaArguments -join " "))
    & $VeaExe @VeaArguments 2>&1 | Tee-Object -FilePath $LogPath -Append
    $ExitCode = $LASTEXITCODE
    if ($AcceptedExitCodes -notcontains $ExitCode) {
        throw "vea 명령이 종료 코드 $ExitCode 로 실패했습니다. 로그: $LogPath"
    }
    return $ExitCode
}

function Get-IndexKey {
    param([object[]]$Indexes)
    return (@($Indexes | ForEach-Object { [int]$_ }) -join ",")
}

function Assert-NoValidationErrors {
    $ValidationPath = Join-Path $ProjectFull "10_REPORTS\validation.json"
    if (-not (Test-Path -LiteralPath $ValidationPath -PathType Leaf)) {
        throw "검증 결과 파일이 없습니다: $ValidationPath"
    }
    $Validation = Get-Content -LiteralPath $ValidationPath -Raw | ConvertFrom-Json
    $Errors = @($Validation.issues | Where-Object { $_.severity -eq "error" })
    if ($Errors.Count -gt 0) {
        $Summary = ($Errors | ForEach-Object { "$($_.code): $($_.message)" }) -join " | "
        throw "VEA 자동 검증 오류가 있어 전사를 중단했습니다: $Summary"
    }
    $ReviewCount = @($Validation.issues | Where-Object { $_.severity -in @("warning", "needs_review") }).Count
    if ($ReviewCount -gt 0) {
        Write-RunLog "자동 검증 오류는 없고 검토 항목 $ReviewCount 건이 있습니다. validation.md와 사람 검수를 확인하세요."
    } else {
        Write-RunLog "VEA 자동 검증 오류와 검토 항목이 없습니다."
    }
}

try {
    if (-not (Test-Path -LiteralPath $VeaExe -PathType Leaf)) {
        throw "Windows VEA가 설치되지 않았습니다. 먼저 scripts\install-windows.ps1을 실행하세요: $VeaExe"
    }
    if (-not (Test-Path -LiteralPath $ProjectJsonPath -PathType Leaf)) {
        throw "VEA 프로젝트의 project.json이 없습니다: $ProjectJsonPath"
    }
    if (-not (Test-Path -LiteralPath $SelectionPath -PathType Leaf) -or -not (Test-Path -LiteralPath $TracksPath -PathType Leaf)) {
        throw "사용자 확인 보이스 선택 또는 트랙 정보가 없습니다. Mac에서 스트림을 확정한 프로젝트 폴더인지 확인하세요."
    }

    New-Item -ItemType Directory -Force -Path $TranscriptsDir | Out-Null
    Write-RunLog "프로젝트: $ProjectFull"
    Write-RunLog "원본: $SourceFull"

    $ProjectData = Get-Content -LiteralPath $ProjectJsonPath -Raw | ConvertFrom-Json
    $Selection = Get-Content -LiteralPath $SelectionPath -Raw | ConvertFrom-Json
    $Tracks = Get-Content -LiteralPath $TracksPath -Raw | ConvertFrom-Json
    if ($Selection.selected_by_user -ne $true) {
        throw "보이스 스트림이 사용자 확인 선택으로 기록되지 않았습니다."
    }
    $SelectedIndexes = @($Selection.selected_global_stream_indexes | ForEach-Object { [int]$_ })
    if ($SelectedIndexes.Count -ne 1) {
        throw "이 실행 스크립트는 컷 정렬 자막용 단일 보이스 스트림을 요구합니다. 저장된 선택: $(Get-IndexKey $SelectedIndexes)"
    }
    $AvailableIndexes = @($Tracks.audio_streams | ForEach-Object { [int]$_.global_index })
    if ($AvailableIndexes -notcontains $SelectedIndexes[0]) {
        throw "선택한 글로벌 오디오 스트림 인덱스 $($SelectedIndexes[0])가 현재 tracks.json에 없습니다."
    }

    $RunSettings = [ordered]@{
        schema_version = 1
        project_id = [string]$ProjectData.project_id
        selected_global_stream_indexes = @($SelectedIndexes)
        model = $Model
        device = $Device
        compute_type = $ComputeType
        language = $Language
        chunk_seconds = $ChunkSeconds
        cpu_fallback = [bool]$CpuFallback
    }
    $RunSettingsJson = ConvertTo-Json -InputObject $RunSettings -Depth 5

    Invoke-Vea -VeaArguments @("doctor")

    if ($Resume) {
        if (-not (Test-Path -LiteralPath $VoiceWavPath -PathType Leaf)) {
            throw "재개에 필요한 컷 정렬 보이스 WAV가 없습니다. 일반 실행으로 먼저 vea audio를 완료하세요: $VoiceWavPath"
        }
        if (-not (Test-Path -LiteralPath $VoiceTracksPath -PathType Leaf)) {
            throw "재개에 필요한 voice_tracks.json이 없습니다: $VoiceTracksPath"
        }
        if (-not (Test-Path -LiteralPath $RunSettingsPath -PathType Leaf)) {
            throw "이 스크립트에서 저장한 실행 설정이 없습니다. 중단 당시와 같은 모델·장치·정밀도·언어·청크 옵션으로 수동 재개하세요."
        }
        $VoiceTracks = Get-Content -LiteralPath $VoiceTracksPath -Raw | ConvertFrom-Json
        $VoiceTrackIndexes = @($VoiceTracks.selected_global_stream_indexes | ForEach-Object { [int]$_ })
        if ((Get-IndexKey $VoiceTrackIndexes) -ne (Get-IndexKey $SelectedIndexes)) {
            throw "기존 roughcut_voice.wav의 스트림 선택이 현재 사용자 선택과 다릅니다. WAV를 다시 만들기 전에 프로젝트를 검토하세요."
        }
        $PreviousSettings = Get-Content -LiteralPath $RunSettingsPath -Raw | ConvertFrom-Json
        $PreviousIndexes = @($PreviousSettings.selected_global_stream_indexes | ForEach-Object { [int]$_ })
        $SettingsMatch = (
            [int]$PreviousSettings.schema_version -eq [int]$RunSettings.schema_version -and
            [string]$PreviousSettings.project_id -eq [string]$RunSettings.project_id -and
            (Get-IndexKey $PreviousIndexes) -eq (Get-IndexKey $SelectedIndexes) -and
            [string]$PreviousSettings.model -eq $Model -and
            [string]$PreviousSettings.device -eq $Device -and
            [string]$PreviousSettings.compute_type -eq $ComputeType -and
            [string]$PreviousSettings.language -eq $Language -and
            [int]$PreviousSettings.chunk_seconds -eq $ChunkSeconds -and
            [bool]$PreviousSettings.cpu_fallback -eq [bool]$CpuFallback
        )
        if (-not $SettingsMatch) {
            throw "재개 옵션이 최초 실행과 다릅니다. 최초 설정을 읽고 같은 옵션으로 다시 실행하세요: $RunSettingsPath"
        }
        Write-RunLog "재개 모드: 기존 WAV와 청크 체크포인트를 보존하고 vea audio 및 relink를 건너뜁니다."
        Invoke-Vea -VeaArguments @("verify", $ProjectFull) -AcceptedExitCodes @(0, 2)
        Assert-NoValidationErrors
    }
    else {
        if (Test-Path -LiteralPath $RunSettingsPath -PathType Leaf) {
            throw "기존 전사 실행 기록이 있습니다. 청크를 보존하려면 -Resume을 사용하세요: $RunSettingsPath"
        }
        $RecordedSource = [string]$ProjectData.source_file
        $RecordedKey = $RecordedSource.Replace("\", "/").Normalize([Text.NormalizationForm]::FormC)
        $CurrentKey = $SourceFull.Replace("\", "/").Normalize([Text.NormalizationForm]::FormC)
        if (-not [string]::Equals($RecordedKey, $CurrentKey, [StringComparison]::OrdinalIgnoreCase)) {
            Write-RunLog "저장된 Mac 경로와 Windows 원본 경로가 달라 SHA-256 확인 relink를 실행합니다."
            Invoke-Vea -VeaArguments @("relink", $ProjectFull, "--source", $SourceFull) -AcceptedExitCodes @(0, 2)
        }
        else {
            Write-RunLog "프로젝트에 기록된 원본 경로와 전달한 경로가 같습니다. relink를 건너뜁니다."
        }

        Invoke-Vea -VeaArguments @("verify", $ProjectFull) -AcceptedExitCodes @(0, 2)
        Assert-NoValidationErrors

        Invoke-Vea -VeaArguments @("audio", $ProjectFull)
        if (-not (Test-Path -LiteralPath $VoiceWavPath -PathType Leaf)) {
            throw "vea audio가 끝났지만 컷 정렬 WAV가 없습니다: $VoiceWavPath"
        }
        Invoke-Vea -VeaArguments @("verify", $ProjectFull) -AcceptedExitCodes @(0, 2)
        Assert-NoValidationErrors
        [System.IO.File]::WriteAllText($RunSettingsPath, $RunSettingsJson, (New-Object System.Text.UTF8Encoding -ArgumentList $false))
    }

    $TranscriptionOptions = @(
        "--model", $Model,
        # Keep retries on the requested model; do not silently switch model size.
        "--fallback-models", $Model,
        "--device", $Device,
        "--compute-type", $ComputeType,
        "--language", $Language,
        "--chunk-seconds", [string]$ChunkSeconds
    )
    if ($CpuFallback) {
        $TranscriptionOptions += "--cpu-fallback"
    }
    if ($Resume) {
        $TranscriptArguments = @("resume", $ProjectFull, "--transcribe") + $TranscriptionOptions
    }
    else {
        $TranscriptArguments = @("transcribe", $ProjectFull) + $TranscriptionOptions
    }
    Invoke-Vea -VeaArguments $TranscriptArguments

    if (-not (Test-Path -LiteralPath $TranscriptSrtPath -PathType Leaf)) {
        throw "전사가 끝났지만 transcript.srt가 없습니다: $TranscriptSrtPath"
    }
    if (Test-Path -LiteralPath $BeforeReviewSrtPath -PathType Leaf) {
        $TranscriptHash = (Get-FileHash -LiteralPath $TranscriptSrtPath -Algorithm SHA256).Hash
        $BeforeReviewHash = (Get-FileHash -LiteralPath $BeforeReviewSrtPath -Algorithm SHA256).Hash
        if ($TranscriptHash -ne $BeforeReviewHash) {
            throw "기존 transcript_before_review.srt가 현재 transcript.srt와 달라 덮어쓰지 않았습니다. 두 파일을 확인하세요."
        }
        Write-RunLog "전·후 비교용 SRT가 이미 있고 transcript.srt와 SHA-256이 같습니다. 기존 파일을 보존합니다."
    }
    else {
        Copy-Item -LiteralPath $TranscriptSrtPath -Destination $BeforeReviewSrtPath
        $TranscriptHash = (Get-FileHash -LiteralPath $TranscriptSrtPath -Algorithm SHA256).Hash
        $BeforeReviewHash = (Get-FileHash -LiteralPath $BeforeReviewSrtPath -Algorithm SHA256).Hash
        if ($TranscriptHash -ne $BeforeReviewHash) {
            throw "transcript_before_review.srt 복사본의 SHA-256이 원본과 다릅니다: $BeforeReviewSrtPath"
        }
        Write-RunLog "전사 직후 SRT를 transcript_before_review.srt로 바이트 보존 복사했습니다."
    }

    Invoke-Vea -VeaArguments @("handoff", $ProjectFull)
    Invoke-Vea -VeaArguments @("verify", $ProjectFull) -AcceptedExitCodes @(0, 2)
    Assert-NoValidationErrors
    Invoke-Vea -VeaArguments @("report", $ProjectFull)
    Invoke-Vea -VeaArguments @("verify", $ProjectFull) -AcceptedExitCodes @(0, 2)
    Assert-NoValidationErrors

    foreach ($RelativePath in @(
        "07_TRANSCRIPTS\transcript.srt",
        "07_TRANSCRIPTS\transcript_before_review.srt",
        "07_TRANSCRIPTS\transcript_after_ai_review.srt",
        "07_TRANSCRIPTS\transcript.json",
        "07_TRANSCRIPTS\transcript.txt",
        "07_TRANSCRIPTS\transcript_review.md",
        "10_REPORTS\validation.md",
        "10_REPORTS\codex_handoff.md",
        "10_REPORTS\transcript_human_review.md",
        "10_REPORTS\windows_transcription_handoff.md"
    )) {
        $ResultPath = Join-Path $ProjectFull $RelativePath
        $ResultLabel = if (Test-Path -LiteralPath $ResultPath -PathType Leaf) { "있음" } else { "없음" }
        Write-RunLog ("결과 {0}: {1}" -f $ResultLabel, $ResultPath)
    }
    if (-not (Test-Path -LiteralPath $AfterAiReviewSrtPath -PathType Leaf)) {
        Write-RunLog "전사 직후/비교용 SRT: transcript.srt + transcript_before_review.srt. Codex AI 검토 후 transcript_after_ai_review.srt를 추가 생성해 두 파일을 사용자에게 함께 제시합니다."
    }
    Write-RunLog "사람 원음 청취 후 확정한 수정만 transcript_reviewed.srt와 transcript_human_review.md에 저장합니다. AI 선택안만으로 사람 검수를 완료 처리하지 않습니다."
    Write-RunLog "실행 로그: $LogPath"
}
catch {
    Write-RunLog ("오류: " + $_.Exception.Message)
    throw
}
