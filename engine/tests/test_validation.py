import hashlib
import json
import unicodedata

from vea.validation import validate_manifest_assets


def test_manifest_asset_validation_detects_tampering_and_missing_files(tmp_path):
    asset = tmp_path / "04_ROUGHCUT" / "cuts.csv"
    asset.parent.mkdir()
    asset.write_bytes(b"original")
    manifest = {
        "manifest_version": 1,
        "assets": [
            {"path": "04_ROUGHCUT/cuts.csv", "size_bytes": 8, "sha256": hashlib.sha256(b"original").hexdigest()},
            {"path": "04_ROUGHCUT/removed.xml", "size_bytes": 0, "sha256": hashlib.sha256(b"").hexdigest()},
            {"path": "../outside.txt", "size_bytes": 0, "sha256": hashlib.sha256(b"").hexdigest()},
        ],
    }
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    assert [issue.code for issue in validate_manifest_assets(tmp_path)] == [
        "manifest_asset_missing",
        "manifest_path_escape",
    ]

    asset.write_bytes(b"tampered")
    issues = validate_manifest_assets(tmp_path)
    assert "manifest_asset_hash_mismatch" in {issue.code for issue in issues}


def test_manifest_asset_validation_resolves_unicode_normalization_differences(tmp_path):
    filename = "synthetic_review_copy.prproj"
    asset = tmp_path / "08_PREMIERE" / filename
    asset.parent.mkdir()
    payload = b"premiere-project"
    asset.write_bytes(payload)
    manifest_path = unicodedata.normalize("NFD", "08_PREMIERE/" + filename)
    manifest = {
        "manifest_version": 1,
        "assets": [
            {
                "path": manifest_path,
                "size_bytes": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
        ],
    }
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    assert validate_manifest_assets(tmp_path) == []
