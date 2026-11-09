"""Bundle the scorer and its pure Python ownership parser without runtime packages."""

import zipfile
import argparse
from pathlib import Path


def build_bundle(source_dir: Path, yaml_source: Path, output: Path) -> None:
    sources = {
        "__main__.py": source_dir / "score_assignees.py",
        "LICENSE.PyYAML": yaml_source / "LICENSE",
    }
    for package, directory in (
        ("owners_yaml", source_dir / "owners_yaml"),
        ("yaml", yaml_source / "lib/yaml"),
    ):
        sources.update({f"{package}/{path.name}": path for path in directory.glob("*.py")})
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("wb") as stream:
        stream.write(b"#!/usr/bin/env -S /usr/bin/python3 -I -S\n")
        with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name, path in sorted(sources.items()):
                archive.writestr(zipfile.ZipInfo(name), path.read_bytes(), compress_type=zipfile.ZIP_DEFLATED)
    output.chmod(0o755)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--yaml-source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    build_bundle(args.source_dir, args.yaml_source, args.output)
