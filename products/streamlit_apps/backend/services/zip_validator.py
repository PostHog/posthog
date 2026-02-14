from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass, field
from io import BytesIO

from products.streamlit_apps.backend.models import AllowedStreamlitPackage

MAX_ZIP_SIZE = 10 * 1024 * 1024  # 10 MB
REQUIREMENT_LINE_RE = re.compile(r"^([a-zA-Z0-9][a-zA-Z0-9._-]*[a-zA-Z0-9]?)(.*)$")


@dataclass
class ValidationResult:
    valid: bool
    errors: list[str] = field(default_factory=list)
    files: list[str] = field(default_factory=list)
    packages: list[str] = field(default_factory=list)
    has_requirements: bool = False


def validate_zip(file: BytesIO) -> ValidationResult:
    """Validate an uploaded zip file for Streamlit app structure and packages."""
    result = ValidationResult(valid=True)

    file.seek(0, 2)
    size = file.tell()
    file.seek(0)
    if size > MAX_ZIP_SIZE:
        result.valid = False
        result.errors.append(f"Zip file too large: {size} bytes (max {MAX_ZIP_SIZE})")
        return result

    try:
        with zipfile.ZipFile(file) as zf:
            result.files = [info.filename for info in zf.infolist() if not info.is_dir()]

            if "app.py" not in result.files:
                result.valid = False
                result.errors.append("Missing required file: app.py")

            if "requirements.txt" in result.files:
                result.has_requirements = True
                requirements_content = zf.read("requirements.txt").decode("utf-8")
                pkg_result = validate_requirements(requirements_content)
                result.packages = pkg_result.packages
                if not pkg_result.valid:
                    result.valid = False
                    result.errors.extend(pkg_result.errors)
    except zipfile.BadZipFile:
        result.valid = False
        result.errors.append("Invalid zip file")

    return result


def validate_requirements(requirements_txt: str) -> ValidationResult:
    """Validate requirements.txt content against the package allowlist."""
    result = ValidationResult(valid=True)
    allowed = set(AllowedStreamlitPackage.objects.values_list("name", flat=True))

    for line in requirements_txt.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("-"):
            continue

        match = REQUIREMENT_LINE_RE.match(line)
        if not match:
            result.valid = False
            result.errors.append(f"Invalid requirement line: {line}")
            continue

        pkg_name = match.group(1).lower()
        result.packages.append(pkg_name)

        if pkg_name not in allowed:
            result.valid = False
            result.errors.append(f"Package not allowed: {pkg_name}")

    return result
