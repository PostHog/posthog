from __future__ import annotations

import os
import json
import hashlib
import subprocess
from pathlib import Path

from unittest.mock import patch

SOURCE_LABEL = "com.posthog.ai-e2e.source-sha"


def build_image(root: Path, output: Path) -> str:
    from products.tasks.backend.logic.services.docker_sandbox import DockerSandbox

    desktop = root / "products/desktop"
    sources = [
        desktop / name
        for name in (".npmrc", "package.json", "pnpm-lock.yaml", "pnpm-workspace.yaml", "scripts/rimraf.mjs")
    ]
    for directory in (
        "patches",
        "packages/agent",
        "packages/harness",
        "packages/shared",
        "packages/git",
        "packages/enricher",
    ):
        for parent, directories, files in os.walk(desktop / directory):
            directories[:] = sorted(set(directories) - {"node_modules", ".turbo", "dist", ".git"})
            sources.extend(Path(parent) / name for name in files)
    sources.append(root / "products/tasks/backend/logic/services/docker_sandbox.py")
    sources.extend((root / "products/tasks/backend/sandbox/images").glob("*"))
    base = json.loads(subprocess.check_output(["docker", "image", "inspect", "posthog-sandbox-base"]))[0]
    digest = hashlib.sha256(base["Id"].encode())
    for path in sorted(sources):
        if path.is_file():
            digest.update(str(path.relative_to(root)).encode())
            digest.update(path.read_bytes())
    fingerprint = digest.hexdigest()
    tag = f"posthog-ai-e2e:{fingerprint}"
    cached = subprocess.run(["docker", "image", "inspect", tag], capture_output=True, text=True)
    if cached.returncode:
        original_run = DockerSandbox._run

        def build(argv: list[str], check: bool = False, timeout: int | None = None) -> subprocess.CompletedProcess[str]:
            if argv[:2] == ["docker", "build"]:
                argv = list(argv)
                argv[argv.index("-t") + 1] = tag
                argv[-1:-1] = ["--label", f"{SOURCE_LABEL}={fingerprint}"]
            try:
                result = original_run(argv, check=check, timeout=timeout)
            except subprocess.CalledProcessError as error:
                (output / "image-build.log").write_text((error.stdout or "") + (error.stderr or ""))
                raise RuntimeError(f"Sandbox build failed; see {output / 'image-build.log'}") from error
            (output / "image-build.log").write_text(result.stdout + result.stderr)
            return result

        with patch.object(DockerSandbox, "_run", side_effect=build):
            DockerSandbox._build_local_image(str(desktop))
    image = json.loads(subprocess.check_output(["docker", "image", "inspect", tag]))[0]
    if image["Config"]["Labels"].get(SOURCE_LABEL) != fingerprint:
        raise RuntimeError("Sandbox image provenance does not match the checkout")
    (output / "image-provenance.json").write_text(
        json.dumps(
            {
                "source_sha": fingerprint,
                "image_id": image["Id"],
                "tag": tag,
                "base_image_id": base["Id"],
                "commit": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
                "lockfile_sha": hashlib.sha256((desktop / "pnpm-lock.yaml").read_bytes()).hexdigest(),
            },
            indent=2,
        )
    )
    return image["Id"]
