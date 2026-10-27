import sys
import json
import shutil
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory

from .routing import DOCS_URL_PREFIX
from .sources import is_test_path

RULE_FILE = Path(__file__).with_name("product-strings.yml")
AST_GREP = shutil.which("ast-grep") or str(Path(sys.executable).with_name("ast-grep"))
SCANNED_ROOTS = ("frontend/src/", "products/")
SCANNED_SUFFIXES = (".ts", ".tsx", ".py")
MIN_WORDS_IN_PRODUCT_STRING = 3
MAX_REMOVED_STRINGS = 20
MAX_QUOTING_PAGES = 3


def removed_product_strings(posthog_checkout: Path, commit_sha: str, touched_paths: list[str]) -> list[str]:
    scanned_paths = [
        path
        for path in touched_paths
        if path.startswith(SCANNED_ROOTS) and path.endswith(SCANNED_SUFFIXES) and not is_test_path(path)
    ]
    if not scanned_paths:
        return []
    with TemporaryDirectory() as before_directory, TemporaryDirectory() as after_directory:
        for path in scanned_paths:
            write_file_at_revision(posthog_checkout, f"{commit_sha}^", path, Path(before_directory))
            write_file_at_revision(posthog_checkout, commit_sha, path, Path(after_directory))
        removed = product_strings(Path(before_directory)) - product_strings(Path(after_directory))
    gone_from_code = [text for text in sorted(removed) if not is_still_in_code(posthog_checkout, text)]
    return gone_from_code[:MAX_REMOVED_STRINGS]


def write_file_at_revision(posthog_checkout: Path, revision: str, path: str, directory: Path) -> None:
    shown = subprocess.run(
        ["git", "-C", str(posthog_checkout), "show", f"{revision}:{path}"], capture_output=True, check=False
    )
    if shown.returncode != 0:
        return
    target = directory / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(shown.stdout)


def product_strings(directory: Path) -> set[str]:
    scanned = subprocess.run(
        [AST_GREP, "scan", "--rule", str(RULE_FILE), "--json=stream", str(directory)],
        capture_output=True,
        text=True,
        check=True,
    )
    found = {" ".join(json.loads(line)["text"].split()) for line in scanned.stdout.splitlines()}
    return {text for text in found if len(text.split()) >= MIN_WORDS_IN_PRODUCT_STRING}


def is_still_in_code(posthog_checkout: Path, text: str) -> bool:
    searched = subprocess.run(
        ["git", "-C", str(posthog_checkout), "grep", "-q", "-F", "-e", text, "--", *SCANNED_ROOTS], check=False
    )
    return searched.returncode == 0


def quoting_page_urls(docs_checkout: Path, removed_strings: list[str]) -> list[str]:
    docs_root = docs_checkout / "contents" / "docs"
    quoting: list[str] = []
    for page_file in sorted(docs_root.rglob("*.md*")):
        page_text = page_file.read_text(errors="ignore")
        if not any(text in page_text for text in removed_strings):
            continue
        quoting.append(docs_page_url(page_file.relative_to(docs_root)))
        if len(quoting) == MAX_QUOTING_PAGES:
            break
    return quoting


def docs_page_url(relative_page_file: Path) -> str:
    page_path = relative_page_file.with_suffix("")
    if page_path.name == "index":
        page_path = page_path.parent
    return f"{DOCS_URL_PREFIX}{page_path.as_posix()}"
