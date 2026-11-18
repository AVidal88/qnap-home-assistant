"""Build a development-only HA bundle with the exact candidate client."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

CLIENT_REVISION = "b2f467a7dc5899d748d901c1d7549436758429d6"
CLIENT_MODULES = (
    "__init__.py",
    "client.py",
    "container_station.py",
    "exceptions.py",
    "models.py",
)
COMPONENT_PATH = "custom_components/qnap"
VENDOR_PATH = f"{COMPONENT_PATH}/_vendor/qnap_client"
CLIENT_IMPORT = re.compile(rb"(?m)^from qnap_client(?=[ .])")


def git_bytes(repository: Path, *arguments: str) -> bytes:
    """Read committed source without relying on working-file line endings."""
    return subprocess.check_output(
        ["git", "-C", str(repository), *arguments], stderr=subprocess.PIPE
    )


def relocate_client_imports(source: bytes) -> tuple[bytes, bool]:
    """Move rewritten SDK imports into the existing relative-import group."""
    imports = [
        node
        for node in ast.parse(source).body
        if isinstance(node, ast.Import | ast.ImportFrom)
    ]
    targets = [
        node
        for node in imports
        if isinstance(node, ast.ImportFrom)
        and node.level == 0
        and (
            node.module == "qnap_client"
            or (node.module or "").startswith("qnap_client.")
        )
    ]
    if not targets:
        return source, False
    relative_import = next(
        (node for node in imports if isinstance(node, ast.ImportFrom) and node.level),
        None,
    )
    insertion = (
        relative_import.lineno - 1 if relative_import else imports[-1].end_lineno
    )
    lines = source.splitlines(keepends=True)
    removed = {
        index for node in targets for index in range(node.lineno - 1, node.end_lineno)
    }
    rewritten = b"\n".join(
        CLIENT_IMPORT.sub(
            b"from ._vendor.qnap_client",
            b"".join(lines[node.lineno - 1 : node.end_lineno]),
        ).rstrip(b"\r\n")
        for node in targets
    )
    before = b"".join(
        line for index, line in enumerate(lines[:insertion]) if index not in removed
    )
    after = b"".join(
        line
        for index, line in enumerate(lines[insertion:], insertion)
        if index not in removed
    )
    before = re.sub(rb"\n{3,}", b"\n\n", before).rstrip(b"\r\n")
    return before + b"\n\n" + rewritten + b"\n" + after, True


def build_bundle(
    component_repo: Path,
    client_repo: Path,
    output: Path,
    *,
    readme_path: str = "docs/quick-install.md",
) -> dict:
    """Package committed files and isolate the SDK inside this test component."""
    component_revision = git_bytes(component_repo, "rev-parse", "HEAD").decode().strip()
    client_revision = (
        git_bytes(client_repo, "rev-parse", "--verify", f"{CLIENT_REVISION}^{{commit}}")
        .decode()
        .strip()
    )
    files: dict[str, bytes] = {}
    transformed: list[str] = []
    tree = git_bytes(
        component_repo, "ls-tree", "-r", "-z", component_revision, "--", COMPONENT_PATH
    )
    for record in tree.split(b"\0"):
        if not record:
            continue
        metadata, raw_name = record.split(b"\t", 1)
        mode, kind, blob = metadata.decode().split()
        name = raw_name.decode("utf-8")
        if mode != "100644" or kind != "blob":
            raise ValueError(f"Unexpected component file type for {name}")
        if "_vendor" in PurePosixPath(name).parts:
            raise ValueError("The source component already contains a vendor directory")
        content = git_bytes(component_repo, "cat-file", "blob", blob)
        if name.endswith(".py"):
            content, relocated = relocate_client_imports(content)
            if relocated:
                transformed.append(name)
        files[name] = content

    manifest_path = f"{COMPONENT_PATH}/manifest.json"
    manifest = json.loads(files[manifest_path])
    manifest["requirements"] = ["xmltodict>=1.0.4"]
    manifest["loggers"] = ["custom_components.qnap._vendor.qnap_client"]
    files[manifest_path] = (json.dumps(manifest, indent=2) + "\n").encode()
    files[f"{COMPONENT_PATH}/_vendor/__init__.py"] = b""

    client_hashes = {}
    for name in (*CLIENT_MODULES, "LICENSE"):
        source_path = "LICENSE" if name == "LICENSE" else f"qnap_client/{name}"
        content = git_bytes(client_repo, "show", f"{client_revision}:{source_path}")
        files[f"{VENDOR_PATH}/{name}"] = content
        client_hashes[source_path] = hashlib.sha256(content).hexdigest()
    files["README-INSTALL.md"] = git_bytes(
        component_repo, "show", f"{component_revision}:{readme_path}"
    )

    provenance = {
        "artifact": "QNAP development bundle",
        "integration_revision": component_revision,
        "client_revision": client_revision,
        "client_namespace": "custom_components.qnap._vendor.qnap_client",
        "readme_source": readme_path,
        "transformations": {
            "relative_client_imports": sorted(transformed),
            "manifest": {
                "requirements": manifest["requirements"],
                "loggers": manifest["loggers"],
            },
        },
        "client_source_sha256": client_hashes,
        "bundle_files_sha256": {
            name: hashlib.sha256(content).hexdigest()
            for name, content in sorted(files.items())
        },
    }
    files["SOURCE.json"] = (json.dumps(provenance, indent=2) + "\n").encode()
    output.parent.mkdir(parents=True, exist_ok=True)
    with (
        output.open("xb") as archive_file,
        ZipFile(
            archive_file, "w", compression=ZIP_DEFLATED, compresslevel=9
        ) as archive,
    ):
        for name, content in sorted(files.items()):
            info = ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            info.compress_type = ZIP_DEFLATED
            archive.writestr(info, content)
    return provenance


def main() -> None:
    """Create the archive without installing or accessing a NAS."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--client-repo", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    source = build_bundle(
        Path(__file__).resolve().parents[1],
        arguments.client_repo.resolve(),
        arguments.output.resolve(),
    )
    print(f"Bundle created at {arguments.output}")
    print(f"Integration {source['integration_revision']}")
    print(f"Client {source['client_revision']}")


if __name__ == "__main__":
    main()
