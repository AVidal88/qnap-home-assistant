"""Check the installable archive without installing HA or dependencies."""

from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from zipfile import ZipFile

from tools.build_development_bundle import (
    CLIENT_MODULES,
    CLIENT_REVISION,
    COMPONENT_PATH,
    VENDOR_PATH,
    build_bundle,
    git_bytes,
)

ROOT = Path(__file__).resolve().parents[1]
CLIENT_REPO = ROOT.parent / "python-qnap-power-pr"


class DevelopmentBundleTests(unittest.TestCase):
    """Exercise real committed source, provenance and output safety."""

    def build(self, output: Path) -> dict:
        return build_bundle(
            ROOT,
            CLIENT_REPO,
            output,
            readme_path="docs/getting-started.md",
        )

    def test_candidate_client_and_relative_imports_are_bundled(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "bundle.zip"
            source = self.build(output)
            with ZipFile(output) as archive:
                names = archive.namelist()
                self.assertTrue(
                    all(
                        name.startswith(f"{COMPONENT_PATH}/")
                        or name in {"SOURCE.json", "README-INSTALL.md"}
                        for name in names
                    )
                )
                for name in CLIENT_MODULES:
                    expected = git_bytes(
                        CLIENT_REPO, "show", f"{CLIENT_REVISION}:qnap_client/{name}"
                    )
                    self.assertEqual(archive.read(f"{VENDOR_PATH}/{name}"), expected)
                self.assertIn(f"{VENDOR_PATH}/LICENSE", names)
                self.assertEqual(source["client_revision"], CLIENT_REVISION)
                self.assertEqual(
                    set(source["transformations"]["relative_client_imports"]),
                    {
                        f"{COMPONENT_PATH}/config_flow.py",
                        f"{COMPONENT_PATH}/coordinator.py",
                        f"{COMPONENT_PATH}/sensor.py",
                        f"{COMPONENT_PATH}/wol.py",
                    },
                )
                for name in source["transformations"]["relative_client_imports"]:
                    content = archive.read(name)
                    self.assertIn(b"from ._vendor.qnap_client", content)
                    self.assertNotIn(b"from qnap_client", content)
                    original = git_bytes(ROOT, "show", f"HEAD:{name}")
                    bodies = []
                    for code in (original, content):
                        tree = ast.parse(code)
                        bodies.append(
                            [
                                ast.dump(node)
                                for node in tree.body
                                if not isinstance(node, ast.Import | ast.ImportFrom)
                            ]
                        )
                    self.assertEqual(bodies[0], bodies[1])
                manifest = json.loads(archive.read(f"{COMPONENT_PATH}/manifest.json"))
                self.assertEqual(manifest["requirements"], ["xmltodict>=1.0.4"])
                for name, digest in source["bundle_files_sha256"].items():
                    self.assertEqual(
                        hashlib.sha256(archive.read(name)).hexdigest(), digest
                    )

    def test_bundle_is_reproducible(self):
        with tempfile.TemporaryDirectory() as temporary:
            first = Path(temporary) / "first.zip"
            second = Path(temporary) / "second.zip"
            self.build(first)
            self.build(second)
            self.assertEqual(first.read_bytes(), second.read_bytes())

    def test_existing_output_is_preserved(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "bundle.zip"
            output.write_bytes(b"existing artifact")
            with self.assertRaises(FileExistsError):
                self.build(output)
            self.assertEqual(output.read_bytes(), b"existing artifact")


if __name__ == "__main__":
    unittest.main()
