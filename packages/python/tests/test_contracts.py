from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = PACKAGE_ROOT.parents[1]
sys.path.insert(0, str(PACKAGE_ROOT))

from vea_contracts import ContractValidationError, load_schema, validate_contract  # noqa: E402


class ContractFixturesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        fixture_path = REPOSITORY_ROOT / "contracts" / "examples" / "contracts-v1.json"
        cls.fixtures = json.loads(fixture_path.read_text(encoding="utf-8"))

    def test_schema_and_examples_cover_the_same_contracts(self) -> None:
        self.assertEqual(set(self.fixtures), set(load_schema()["$defs"]))

    def test_every_shared_fixture_passes(self) -> None:
        for kind, value in self.fixtures.items():
            with self.subTest(contract=kind):
                validate_contract(kind, value)

    def test_asset_paths_cannot_escape_the_workspace(self) -> None:
        asset = dict(self.fixtures["MediaAsset"], relative_path="../../outside.mov")
        with self.assertRaises(ContractValidationError):
            validate_contract("MediaAsset", asset)

    def test_absolute_paths_are_rejected(self) -> None:
        manifest = dict(self.fixtures["ProjectManifest"], asset_index="C:/private/assets.json")
        with self.assertRaises(ContractValidationError):
            validate_contract("ProjectManifest", manifest)

    def test_timeline_requires_declared_tracks_and_positive_ranges(self) -> None:
        timeline = json.loads(json.dumps(self.fixtures["TimelineIR"]))
        timeline["clips"][0]["track_id"] = "missing-track"
        with self.assertRaises(ContractValidationError) as context:
            validate_contract("TimelineIR", timeline)
        self.assertIn("track_id is not declared", str(context.exception))

    def test_timeline_rejects_empty_frame_ranges(self) -> None:
        timeline = json.loads(json.dumps(self.fixtures["TimelineIR"]))
        timeline["clips"][0]["start_frame"] = 120
        with self.assertRaises(ContractValidationError) as context:
            validate_contract("TimelineIR", timeline)
        self.assertIn("must end after it starts", str(context.exception))

    def test_recipe_must_keep_preview_approval_and_source_preservation(self) -> None:
        recipe = json.loads(json.dumps(self.fixtures["EditingRecipe"]))
        recipe["policies"]["approval_required"] = False
        with self.assertRaises(ContractValidationError):
            validate_contract("EditingRecipe", recipe)


if __name__ == "__main__":
    unittest.main()
