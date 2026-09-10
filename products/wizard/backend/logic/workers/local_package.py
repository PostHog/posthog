import io
import json
import tarfile
from pathlib import Path

from products.wizard.backend.logic.workers.config import LOCAL_WIZARD_SOURCE_ENTRIES


class InvalidLocalWizardSourceError(Exception):
    pass


def build_local_wizard_source_archive(source_root: Path) -> bytes:
    _validate_local_wizard_source(source_root)

    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        for entry in LOCAL_WIZARD_SOURCE_ENTRIES:
            path = source_root / entry
            if path.exists():
                archive.add(path, arcname=entry, recursive=True, filter=_exclude_links)

    return buffer.getvalue()


def _validate_local_wizard_source(source_root: Path) -> None:
    if not source_root.is_dir():
        raise InvalidLocalWizardSourceError(f"Local Wizard source directory does not exist: {source_root}")

    try:
        package = json.loads((source_root / "package.json").read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise InvalidLocalWizardSourceError(f"Local Wizard package manifest is invalid: {source_root}") from error

    if not isinstance(package, dict) or package.get("name") != "@posthog/wizard":
        raise InvalidLocalWizardSourceError(f"Local Wizard package manifest is invalid: {source_root}")

    if not (source_root / "pnpm-lock.yaml").is_file():
        raise InvalidLocalWizardSourceError(f"Local Wizard lockfile does not exist: {source_root}")


def _exclude_links(info: tarfile.TarInfo) -> tarfile.TarInfo | None:
    return None if info.issym() or info.islnk() else info
