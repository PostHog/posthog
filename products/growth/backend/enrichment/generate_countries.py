"""Regenerate the COUNTRY_NAME_TO_ISO_CODE map in countries.py from the frontend source.

The map inverts frontend/src/lib/utils/country.ts (COUNTRY_CODE_TO_LONG_NAME) so the
backend and frontend agree on country naming. Run this after the frontend map changes:

    python products/growth/backend/enrichment/generate_countries.py

Only the generated map is rewritten; the hand-maintained provider aliases (_ALIASES) and
the lookup function in countries.py are left untouched.
"""

import re
from pathlib import Path

_THIS_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _THIS_DIR.parents[3]
_COUNTRY_TS = _REPO_ROOT / "frontend/src/lib/utils/country.ts"
_COUNTRIES_PY = _THIS_DIR / "countries.py"

_MAP_NAME = "COUNTRY_NAME_TO_ISO_CODE"


def _parse_long_names(ts_source: str) -> dict[str, str]:
    block = re.search(r"COUNTRY_CODE_TO_LONG_NAME[^{]*\{(.*?)\n\}", ts_source, re.DOTALL)
    if not block:
        raise SystemExit("Could not find COUNTRY_CODE_TO_LONG_NAME in country.ts")
    # Values use single or double quotes (double when the name contains an apostrophe).
    matches = re.findall(r"""([A-Z]{2}):\s*(['"])((?:(?!\2)[^\\]|\\.)*)\2""", block.group(1))
    if not matches:
        raise SystemExit("Parsed no country entries from COUNTRY_CODE_TO_LONG_NAME")
    return {code: name.replace("\\'", "'").replace('\\"', '"') for code, _quote, name in matches}


def _render_map(code_to_name: dict[str, str]) -> str:
    items = sorted((name.lower(), code) for code, name in code_to_name.items())
    lines = "\n".join(f'    "{name}": "{code}",' for name, code in items)
    return f"{_MAP_NAME}: dict[str, str] = {{\n{lines}\n}}"


def main() -> None:
    code_to_name = _parse_long_names(_COUNTRY_TS.read_text())
    rendered = _render_map(code_to_name)
    py_source = _COUNTRIES_PY.read_text()
    new_source, count = re.subn(
        rf"{_MAP_NAME}: dict\[str, str\] = \{{.*?\n\}}",
        lambda _: rendered,
        py_source,
        count=1,
        flags=re.DOTALL,
    )
    if count != 1:
        raise SystemExit(f"Could not locate {_MAP_NAME} block in countries.py")
    _COUNTRIES_PY.write_text(new_source)


if __name__ == "__main__":
    main()
