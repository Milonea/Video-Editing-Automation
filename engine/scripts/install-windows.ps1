param(
    [switch]$WithWhisper,
    [switch]$WithCuda,
    [switch]$WithDev
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$VenvDir = Join-Path $RepoRoot ".venv-windows"
$VenvPython = Join-Path $VenvDir "Scripts\python.exe"
$VeaExe = Join-Path $VenvDir "Scripts\vea.exe"

if ($WithCuda -and -not $WithWhisper) {
    throw "-WithCuda를 사용하려면 -WithWhisper도 지정하세요."
}

$MissingMediaTools = @("ffmpeg", "ffprobe") | Where-Object { -not (Get-Command $_ -ErrorAction SilentlyContinue) }
if ($MissingMediaTools.Count -gt 0) {
    Write-Warning "FFmpeg/FFprobe가 없어 미디어 명령을 사용할 수 없습니다. 필요한 경우 설치 후 PATH에 추가하세요."
}

Push-Location $RepoRoot
try {

$PythonLauncher = Get-Command py -ErrorAction SilentlyContinue
if ($PythonLauncher) {
    & $PythonLauncher.Source -3.12 --version
    if ($LASTEXITCODE -ne 0) {
        throw "Python 3.12가 필요합니다. python.org에서 64-bit Python 3.12를 설치하세요."
    }
    & $PythonLauncher.Source -3.12 -m venv $VenvDir
    if ($LASTEXITCODE -ne 0) {
        throw "Python 가상환경을 만들지 못했습니다."
    }
} else {
    $PythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if (-not $PythonCommand) {
        throw "Python 3.11 이상을 설치하세요."
    }
    $PythonVersion = & $PythonCommand.Source -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
    if ($LASTEXITCODE -ne 0 -or [version]$PythonVersion -lt [version]"3.11") {
        throw "Python 3.11 이상이 필요합니다."
    }
    & $PythonCommand.Source -m venv $VenvDir
    if ($LASTEXITCODE -ne 0) {
        throw "Python 가상환경을 만들지 못했습니다."
    }
}

if (-not (Test-Path $VenvPython)) {
    throw "가상환경 Python을 찾지 못했습니다: $VenvPython"
}

$Features = @()
if ($WithWhisper) {
    if ($WithCuda) {
        $Features += "windows"
    } else {
        $Features += "windows-cpu"
    }
}
if ($WithDev) {
    $Features += "dev"
}
$Extra = "."
if ($Features.Count -gt 0) {
    $Extra = ".[" + ($Features -join ",") + "]"
}
& $VenvPython -m pip install -e $Extra
if ($LASTEXITCODE -ne 0) {
    throw "VEA 의존성 설치에 실패했습니다."
}

if ($WithCuda) {
    Write-Host "프로젝트 가상환경에 CUDA 12 런타임을 설치했습니다. NVIDIA GPU 드라이버를 확인하세요."
} elseif ($WithWhisper) {
    Write-Host "CPU Whisper 의존성을 선택 설치했습니다."
} else {
    Write-Host "가벼운 기본 설치를 완료했습니다. Whisper와 CUDA는 요청한 경우에만 설치됩니다."
}
& $VeaExe doctor
if ($LASTEXITCODE -ne 0) {
    throw "vea doctor에서 오류가 발생했습니다."
}
Write-Host "Windows 가상환경: $VenvDir"
$ActivateScript = Join-Path $VenvDir "Scripts\Activate.ps1"
Write-Host ('활성화: & "{0}"' -f $ActivateScript)
}
finally {
    Pop-Location
}
