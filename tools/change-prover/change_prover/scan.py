"""Scan the packages a change adds to a lockfile with GuardDog."""

from __future__ import annotations

import os
import re
import sys
import json
import time
import signal
import hashlib
import tomllib
import tempfile
import subprocess
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

import yaml

GUARDDOG = [sys.executable, "-m", "guarddog"]
SCAN_TIMEOUT_SECONDS = 180
BATCH_DEADLINE_SECONDS = 14 * 60
SCAN_WORKERS = 8
# GuardDog cannot download a release the registry has only just published, so a failed download is tried again.
DOWNLOAD_RULE = "download-package"
DOWNLOAD_ATTEMPTS = 4
DOWNLOAD_RETRY_SECONDS = 30
MAX_PACKAGES = 300
BLOCKING_LABEL = "high_risk"
CLEAN_LABEL = "no_risks_detected"
NOT_SCANNED = "not_scanned"
# The labels a gate passes. A label GuardDog adds in a later version is refused until it is listed here.
PASSING_LABELS = (CLEAN_LABEL, "low", "suspicious")
SCANNER_PATH = "tools/change-prover/change_prover/scan.py"

NPM_NAME = re.compile(r"(@[A-Za-z0-9][A-Za-z0-9._~-]*/)?[A-Za-z0-9][A-Za-z0-9._~-]*")
PLAIN_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
GO_MODULE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._~-]*(/[A-Za-z0-9][A-Za-z0-9._~-]*)*")
VERSION = re.compile(r"[0-9][0-9A-Za-z.+!-]*")
GO_VERSION = re.compile(r"v[0-9][0-9A-Za-z.+-]*")
NAME_PATTERNS = {"npm": NPM_NAME, "pypi": PLAIN_NAME, "crates": PLAIN_NAME, "go": GO_MODULE}
VERSION_PATTERNS = {"npm": VERSION, "pypi": VERSION, "crates": VERSION, "go": GO_VERSION}
GO_TOKEN = re.compile(r"\(|\)|[^\s()]+")
COMMIT_SHA = re.compile(r"[0-9a-f]{40}")
PYPI_REGISTRY = "https://pypi.org/simple"
CRATES_REGISTRIES = ("registry+https://github.com/rust-lang/crates.io-index", "sparse+https://index.crates.io/")
LOCAL_UV_SOURCES = ("editable", "virtual", "directory", "path")
REGISTRY_RESOLUTION_KEYS = {"integrity"}
YAML_LOADER = getattr(yaml, "CSafeLoader", yaml.SafeLoader)

EXCLUDED_RULES: dict[str, tuple[str, ...]] = {
    "npm": ("bundled_binary", "metadata_mismatch", "potentially_compromised_email_domain"),
    "pypi": ("bundled_binary", "repository_integrity_mismatch", "potentially_compromised_email_domain"),
    "crates": (),
    "go": (),
}
SCANNER_SELF_CHECK = (
    ("npm", "is-stream", "3.0.0"),
    ("pypi", "idna", "3.10"),
    ("crates", "itoa", "1.0.15"),
    ("go", "github.com/google/uuid", "v1.6.0"),
)


@dataclass(frozen=True, order=True)
class Package:
    ecosystem: str
    name: str
    version: str
    source: str = ""

    @property
    def spec(self) -> str:
        return f"{self.name}@{self.version}"

    @property
    def scannable(self) -> bool:
        return bool(
            not self.source
            and NAME_PATTERNS[self.ecosystem].fullmatch(self.name)
            and VERSION_PATTERNS[self.ecosystem].fullmatch(self.version)
        )


@dataclass(frozen=True)
class Finding:
    package: Package
    label: str
    score: float
    rules: tuple[str, ...]


@dataclass(frozen=True)
class Location:
    path: str
    line: int


# The dependency proof compares lockfiles as parsed YAML, so this reader parses them too. A reader
# that matched lines would see a different file than the proof, for example when a comment
# follows `packages:`, and every package it misses would pass the gate unscanned.
def pnpm_packages(lockfile: str) -> set[Package]:
    if not lockfile:
        return set()
    document = yaml.load(lockfile, Loader=YAML_LOADER)
    entries = document.get("packages") if isinstance(document, dict) else None
    if not isinstance(entries, dict | None):
        raise ValueError("pnpm-lock.yaml has a `packages` entry that is not a mapping")
    slash_separated_keys = float(str(document.get("lockfileVersion", 9))) < 6
    packages: set[Package] = set()
    for key, entry in (entries or {}).items():
        name, version = pnpm_key(str(key), slash_separated_keys)
        if name and version:
            packages.add(Package("npm", name, version, pnpm_source(entry)))
    return packages


def pnpm_key(key: str, slash_separated: bool) -> tuple[str, str]:
    key = key.removeprefix("/").split("(", 1)[0]
    if slash_separated:
        name, _, version = key.rpartition("/")
        return name, version.split("_", 1)[0]
    name, _, version = key.rpartition("@")
    return name, version


def pnpm_source(entry: object) -> str:
    resolution = entry.get("resolution") if isinstance(entry, dict) else None
    if not isinstance(resolution, dict) or set(resolution) <= REGISTRY_RESOLUTION_KEYS:
        return ""
    return json.dumps(resolution, sort_keys=True)


def uv_packages(lockfile: str) -> set[Package]:
    packages: set[Package] = set()
    for entry in tomllib.loads(lockfile).get("package", []):
        source = entry.get("source", {})
        if any(kind in source for kind in LOCAL_UV_SOURCES):
            continue
        foreign = "" if source.get("registry") == PYPI_REGISTRY else json.dumps(source, sort_keys=True)
        packages.add(Package("pypi", entry["name"], entry.get("version", ""), foreign))
    return packages


def cargo_packages(lockfile: str) -> set[Package]:
    packages: set[Package] = set()
    for entry in tomllib.loads(lockfile).get("package", []):
        source = entry.get("source")
        if source is None:
            continue
        foreign = "" if source in CRATES_REGISTRIES else source
        packages.add(Package("crates", entry["name"], entry["version"], foreign))
    return packages


def go_directives(manifest: str) -> Iterable[tuple[str, list[str]]]:
    block = ""
    for line in manifest.splitlines():
        tokens = [token.strip('"`') for token in GO_TOKEN.findall(line.split("//", 1)[0])]
        if not tokens:
            continue
        if block:
            if tokens == [")"]:
                block = ""
            else:
                yield block, tokens
        elif tokens[1:] == ["("]:
            block = tokens[0]
        else:
            yield tokens[0], tokens[1:]


def go_packages(manifest: str) -> set[Package]:
    packages: set[Package] = set()
    for directive, arguments in go_directives(manifest):
        if directive == "replace" and "=>" in arguments:
            arguments = arguments[arguments.index("=>") + 1 :]
        elif directive != "require":
            continue
        if len(arguments) >= 2:
            packages.add(Package("go", arguments[0], arguments[1]))
    return packages


LOCKFILE_READERS: dict[str, Callable[[str], set[Package]]] = {
    "pnpm-lock.yaml": pnpm_packages,
    "uv.lock": uv_packages,
    "Cargo.lock": cargo_packages,
    "go.mod": go_packages,
}


def added_packages(filename: str, base: str, head: str) -> set[Package]:
    read = LOCKFILE_READERS[filename]
    return read(head) - read(base)


def git(*args: str) -> str:
    command = ["git", "-c", "core.hooksPath=/dev/null", *args]
    return subprocess.run(command, check=True, capture_output=True, text=True).stdout


def blob(ref: str, path: str) -> str:
    if not git("ls-tree", ref, "--", path):
        return ""
    return git("cat-file", "blob", f"{ref}:{path}")


def changed_lockfiles(base: str, head: str) -> list[str]:
    paths = git("diff", "--name-only", "--no-renames", "-z", base, head).split("\0")
    return [path for path in paths if path.rpartition("/")[2] in LOCKFILE_READERS]


def not_scanned(package: Package, reason: str) -> Finding:
    sys.stderr.write(f"{package.ecosystem} {package.spec} was not scanned: {reason}\n")
    return Finding(package, NOT_SCANNED, 0.0, ())


def scan(package: Package, deadline: float) -> Finding:
    for attempt in range(1, DOWNLOAD_ATTEMPTS + 1):
        finding, download_failed = scan_once(package, deadline)
        retry_fits = deadline - time.monotonic() > DOWNLOAD_RETRY_SECONDS
        if not download_failed or attempt == DOWNLOAD_ATTEMPTS or not retry_fits:
            return finding
        time.sleep(DOWNLOAD_RETRY_SECONDS)
    raise AssertionError("unreachable")


def scan_once(package: Package, deadline: float) -> tuple[Finding, bool]:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        return not_scanned(package, "the batch ran out of time"), False
    excluded = [flag for rule in EXCLUDED_RULES[package.ecosystem] for flag in ("--exclude-rules", rule)]
    command = [
        *GUARDDOG,
        package.ecosystem,
        "scan",
        package.name,
        "--version",
        package.version,
        "--output-format",
        "json",
        *excluded,
    ]
    with tempfile.TemporaryDirectory(prefix="guarddog-") as scratch:
        env = {name: value for name, value in os.environ.items() if not name.startswith("GITHUB_")}
        env["TMPDIR"] = scratch
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            env=env,
            cwd=scratch,
            start_new_session=True,
        )
        try:
            stdout, _ = process.communicate(timeout=min(SCAN_TIMEOUT_SECONDS, remaining))
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()
            return not_scanned(package, "GuardDog timed out"), False
    try:
        report = json.loads(stdout)
        # GuardDog scores only the rules that ran, so a rule that failed can hide what it would find.
        if report["errors"]:
            failed_rules = ", ".join(sorted(rule for rule in report["errors"] if PLAIN_NAME.fullmatch(str(rule))))
            return not_scanned(package, f"GuardDog rules failed: {failed_rules or 'unnamed'}"), DOWNLOAD_RULE in report[
                "errors"
            ]
        risk = report["risk_score"]
        rules = tuple(
            sorted(rule for rule, hits in report["results"].items() if hits and not rule.startswith("capability"))
        )
        return Finding(package, str(risk["label"]), float(risk["score"]), rules), False
    except (ValueError, KeyError, TypeError):
        return not_scanned(package, f"GuardDog exited with status {process.returncode} without a usable report"), False


def scan_all(packages: Iterable[Package]) -> list[Finding]:
    deadline = time.monotonic() + BATCH_DEADLINE_SECONDS
    with ThreadPoolExecutor(max_workers=SCAN_WORKERS) as pool:
        return list(pool.map(lambda package: scan(package, deadline), packages))


def summary(findings: list[Finding], skipped: list[Package]) -> str:
    counts: dict[str, int] = {}
    for finding in findings:
        counts[finding.label] = counts.get(finding.label, 0) + 1
    lines = ["### Dependency scan", "", f"Scanned {len(findings)} added or changed packages with GuardDog.", ""]
    lines += [f"- `{label}`: {count}" for label, count in sorted(counts.items())]
    if skipped:
        lines.append(
            f"- not scanned (not a registry release, or over the {MAX_PACKAGES} package limit): {len(skipped)}"
        )
    flagged = sorted(
        (finding for finding in findings if finding.label != CLEAN_LABEL), key=lambda finding: -finding.score
    )
    if flagged:
        lines += ["", "| Package | Ecosystem | Label | Score | Rules |", "| --- | --- | --- | --- | --- |"]
        lines += [
            f"| `{finding.package.spec}` | {finding.package.ecosystem} | `{finding.label}` | {finding.score:.1f} | {', '.join(finding.rules)} |"
            for finding in flagged
        ]
    return "\n".join(lines) + "\n"


def findings_output(findings: list[Finding], skipped: list[Package]) -> str:
    flagged = sorted(
        (finding for finding in findings if finding.label != CLEAN_LABEL), key=lambda finding: -finding.score
    )
    return json.dumps(
        {
            "scanned": len(findings),
            "skipped": len(skipped),
            "flagged": [
                {
                    "ecosystem": finding.package.ecosystem,
                    "package": finding.package.spec,
                    "label": finding.label,
                    "score": finding.score,
                    "rules": list(finding.rules),
                }
                for finding in flagged
            ],
        }
    )


def line_of(lockfile: str, package: Package) -> int:
    lines = lockfile.splitlines()
    for number, line in enumerate(lines, start=1):
        stripped = line.strip()
        if package.ecosystem == "npm":
            found = stripped.strip("':") == package.spec
        elif package.ecosystem == "go":
            tokens = GO_TOKEN.findall(stripped.split("//", 1)[0])
            found = any(tokens[index : index + 2] == [package.name, package.version] for index in range(len(tokens)))
        else:
            following = lines[number].strip() if number < len(lines) else ""
            found = stripped == f'name = "{package.name}"' and following == f'version = "{package.version}"'
        if found:
            return number
    return 1


def sarif_output(findings: list[Finding], locations: dict[Package, Location]) -> str:
    results: list[dict[str, object]] = []
    rule_ids: set[str] = set()
    for finding in findings:
        if finding.label != BLOCKING_LABEL:
            continue
        package = finding.package
        location = locations.get(package, Location(SCANNER_PATH, 1))
        for rule in finding.rules or (BLOCKING_LABEL,):
            identity = f"{package.ecosystem}/{package.name}/{rule}"
            rule_id = f"{package.ecosystem}/{rule}"
            rule_ids.add(rule_id)
            results.append(
                {
                    "ruleId": rule_id,
                    "level": "warning",
                    "message": {
                        "text": f"{package.spec} ({package.ecosystem}) is {finding.label} with score {finding.score:.1f}: {rule}"
                    },
                    "locations": [
                        {
                            "physicalLocation": {
                                "artifactLocation": {"uri": location.path},
                                "region": {"startLine": location.line},
                            }
                        }
                    ],
                    "partialFingerprints": {
                        "primaryLocationLineHash": f"{hashlib.sha256(identity.encode()).hexdigest()[:16]}:1"
                    },
                }
            )
    return json.dumps(
        {
            "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
            "version": "2.1.0",
            "runs": [
                {
                    "tool": {
                        "driver": {
                            "name": "GuardDog",
                            "informationUri": "https://github.com/DataDog/guarddog",
                            "rules": [
                                {"id": rule_id, "shortDescription": {"text": f"GuardDog rule {rule_id}"}}
                                for rule_id in sorted(rule_ids)
                            ],
                        }
                    },
                    "results": results,
                }
            ],
        }
    )


def is_clean(findings: list[Finding], skipped: list[Package]) -> bool:
    return not skipped and all(finding.label in PASSING_LABELS for finding in findings)


def scanner_is_broken(findings: list[Finding]) -> bool:
    return bool(findings) and all(finding.label == NOT_SCANNED for finding in findings)


@dataclass(frozen=True)
class ReportRequest:
    base: str
    head: str
    findings_path: str | None
    sarif_path: str | None
    summary_path: str | None


@dataclass(frozen=True)
class GateRequest:
    base: str
    head: str
    output_path: str
    summary_path: str | None


def scan_additions(
    base: str, head: str, fallback: Iterable[Package], summary_path: str | None
) -> tuple[list[Finding], list[Package], dict[Package, Location]]:
    locations: dict[Package, Location] = {}
    lockfiles = changed_lockfiles(base, head)
    for path in lockfiles:
        head_lockfile = blob(head, path)
        for package in added_packages(path.rpartition("/")[2], blob(base, path), head_lockfile):
            locations.setdefault(package, Location(path, line_of(head_lockfile, package)))
    candidates = sorted(locations) if lockfiles else list(fallback)
    to_scan = [package for package in candidates if package.scannable][:MAX_PACKAGES]
    skipped = [package for package in candidates if package not in to_scan]
    findings = scan_all(to_scan)
    report = summary(findings, skipped)
    sys.stdout.write(report)
    if summary_path:
        with open(summary_path, "a") as handle:
            handle.write(report)
    return findings, skipped, locations


def report(request: ReportRequest) -> int:
    findings, skipped, locations = scan_additions(
        request.base, request.head, [Package(*package) for package in SCANNER_SELF_CHECK], request.summary_path
    )
    for finding in findings:
        if finding.label == BLOCKING_LABEL:
            sys.stdout.write(
                f"::warning title=Dependency scan::{finding.package.ecosystem} {finding.package.spec} is {finding.label}\n"
            )
    if request.findings_path:
        Path(request.findings_path).write_text(findings_output(findings, skipped))
    if request.sarif_path:
        Path(request.sarif_path).write_text(sarif_output(findings, locations))
    return 1 if scanner_is_broken(findings) else 0


def gate(request: GateRequest) -> int:
    base, head = request.base, request.head
    if not (COMMIT_SHA.fullmatch(base) and COMMIT_SHA.fullmatch(head)):
        raise SystemExit("the merge base or the head is not a commit id")
    git("fetch", "--no-tags", "--depth=1", "origin", base, head)
    findings, skipped, _ = scan_additions(base, head, [], request.summary_path)
    clean = is_clean(findings, skipped)
    with Path(request.output_path).open("a") as handle:
        handle.write(f"clean={'true' if clean else 'false'}\n")
    # A scanner that fails on every package fails the job, so the outage shows instead of a neutral proof.
    return 1 if scanner_is_broken(findings) else 0
