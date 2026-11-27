import json
import base64
from typing import Any

import pytest

from change_prover import prove as prover
from change_prover.core import policy, python_sdk
from change_prover.core.policy import Refused

BASE, HEAD = "b" * 40, "a" * 40
OLD, NEW = "7.91.1", "7.91.2"
FILES_HOST = "https://files.pythonhosted.org/packages/00/00"
PUBLISHER = {"environment": None, "kind": "GitHub", "repository": "PostHog/posthog-python", "workflow": "release.yml"}


def pyproject(version: str, extra: str = "") -> bytes:
    return (
        f'[project]\nname = "posthog"\ndependencies = [\n    "django~=6.1.3",\n    "posthoganalytics=={version}",\n]\n'
        f'\n[tool.uv]\nexclude-newer = "7 days"\nexclude-newer-package = {{ posthoganalytics = false }}\n{extra}'
    ).encode()


def requirements(version: str) -> bytes:
    return f"requests==2.33.1\nposthog>={version}\n".encode()


def artifact(name: str, version: str, kind: str) -> tuple[str, int]:
    filename = f"{name}-{version}.tar.gz" if kind == "sdist" else f"{name}-{version}-py3-none-any.whl"
    return filename, len(filename) * 1000


def digest(filename: str) -> str:
    return filename.encode().hex()[:64].ljust(64, "0")


def lock_entry(name: str, version: str, wheels: bool = True) -> str:
    sdist, size = artifact(name, version, "sdist")
    entry = (
        f'[[package]]\nname = "{name}"\nversion = "{version}"\nsource = {{ registry = "https://pypi.org/simple" }}\n'
        f'dependencies = [\n    {{ name = "requests" }},\n]\n'
        f'sdist = {{ url = "{FILES_HOST}/{sdist}", hash = "sha256:{digest(sdist)}", size = {size} }}\n'
    )
    if wheels:
        wheel, wheel_size = artifact(name, version, "wheel")
        entry += f'wheels = [\n    {{ url = "{FILES_HOST}/{wheel}", hash = "sha256:{digest(wheel)}", size = {wheel_size} }},\n]\n'
    return entry


def lock(version: str, entry: str | None = None, extra: str = "") -> bytes:
    return (
        'version = 1\nrevision = 5\nrequires-python = ">=3.12"\n\n'
        '[[package]]\nname = "posthog"\nversion = "0.0.0"\nsource = { virtual = "." }\n'
        'dependencies = [\n    { name = "django" },\n    { name = "posthoganalytics" },\n]\n\n'
        f'[package.metadata]\nrequires-dist = [\n    {{ name = "django", specifier = "~=6.1.3" }},\n'
        f'    {{ name = "posthoganalytics", specifier = "=={version}" }},\n]\n\n'
        f"{entry if entry is not None else lock_entry('posthoganalytics', version)}\n{extra}"
    ).encode()


def tree(version: str, **files: bytes) -> dict[str, bytes]:
    return {
        "pyproject.toml": pyproject(version),
        "uv.lock": lock(version),
        "tools/requirements.txt": requirements(version),
        **files,
    }


def release(name: str, version: str, requires: list[str] | None = None, extra: str = "extra == ") -> dict[str, Any]:
    urls = []
    for kind in ("sdist", "wheel"):
        filename, size = artifact(name, version, kind)
        urls.append(
            {
                "filename": filename,
                "url": f"{FILES_HOST}/{filename}",
                "size": size,
                "digests": {"sha256": digest(filename)},
                "yanked": False,
            }
        )
    core = requires if requires is not None else ["requests<3.0,>=2.7"]
    return {
        "info": {"requires_dist": [*core, f'pytest; {extra}"test{version}"'], "requires_python": ">=3.10"},
        "urls": urls,
    }


def provenance(filename: str, publisher: dict[str, Any] = PUBLISHER, subject: str | None = None) -> dict[str, Any]:
    statement = {"subject": [{"name": subject or filename, "digest": {"sha256": digest(subject or filename)}}]}
    envelope = {"statement": base64.b64encode(json.dumps(statement).encode()).decode(), "signature": "x"}
    return {"attestation_bundles": [{"publisher": publisher, "attestations": [{"envelope": envelope}]}]}


class FakePyPI(prover.PyPI):
    def __init__(self, **overrides: Any) -> None:
        self.documents: dict[str, Any] = {}
        for name in python_sdk.FIRST_PARTY:
            for version in (OLD, NEW):
                self.documents[f"pypi/{name}/{version}/json"] = release(name, version)
                for kind in ("sdist", "wheel"):
                    filename, _ = artifact(name, version, kind)
                    self.documents[f"integrity/{name}/{version}/{filename}/provenance"] = provenance(filename)
        self.documents.update(overrides)

    def get(self, path: str) -> Any | None:
        return self.documents.get(path)


def prove(head: dict[str, bytes], pypi: FakePyPI | None = None, base: dict[str, bytes] | None = None) -> list[str]:
    trees = {BASE: base or tree(OLD), HEAD: head}
    changes = [
        policy.ChangedFile("M", path) for path in sorted(trees[HEAD]) if trees[BASE].get(path) != trees[HEAD].get(path)
    ]
    paths = policy.eligible_paths(changes, policy.PYTHON_SDK_LANE)
    prover.prove_python_sdk(paths, lambda ref, path: trees[ref][path], BASE, HEAD, pypi or FakePyPI())
    return paths


WHEEL, _ = artifact("posthoganalytics", NEW, "wheel")
STAYING_SDIST, _ = artifact("posthog", OLD, "sdist")


@pytest.mark.parametrize(
    ("base", "pypi"),
    [
        (None, None),
        # A lagging floor compares the requirements of the release the lockfile held, or none when no lockfile holds it.
        (tree(OLD, **{"pyproject.toml": pyproject(OLD).replace(OLD.encode(), b"7.50.0")}), None),
        (tree(OLD, **{"tools/requirements.txt": requirements("7.50.0")}), None),
        (
            None,
            FakePyPI(
                **{
                    f"pypi/posthoganalytics/{version}/json": release("posthoganalytics", version, extra="extra==")
                    for version in (OLD, NEW)
                }
            ),
        ),
    ],
)
def test_a_first_party_bump_is_proved(base: dict[str, bytes] | None, pypi: FakePyPI | None) -> None:
    assert prove(tree(NEW), pypi, base) == ["pyproject.toml", "tools/requirements.txt", "uv.lock"]


def tool_entry(version: str) -> str:
    return (
        '[[package]]\nname = "tool"\nversion = "1.0.0"\nsource = { editable = "tool" }\n\n'
        f'[package.metadata]\nrequires-dist = [{{ name = "posthoganalytics", specifier = "=={version}" }}]\n'
    )


@pytest.mark.parametrize(
    ("base", "head", "reason"),
    [
        (
            tree(OLD, **{"uv.lock": lock(OLD, extra=lock_entry("posthog", OLD))}),
            tree(
                NEW, **{"uv.lock": lock(NEW, extra=lock_entry("posthog", OLD).replace(digest(STAYING_SDIST), "f" * 64))}
            ),
            "changes the files of posthog without moving its version",
        ),
        (
            tree(OLD, **{"uv.lock": lock(OLD, extra=tool_entry(OLD))}),
            tree(NEW, **{"uv.lock": lock(NEW, extra=tool_entry(OLD))}),
            "names posthoganalytics at more than one version",
        ),
        (
            tree(OLD, **{"tools/requirements.txt": f"posthog>={OLD}\n".encode()}),
            tree(NEW, **{"tools/requirements.txt": f"posthog=={NEW}\n".encode()}),
            "changes more than a version",
        ),
    ],
)
def test_a_bump_that_differs_from_its_base_beyond_the_version_is_refused(
    base: dict[str, bytes], head: dict[str, bytes], reason: str
) -> None:
    with pytest.raises(Refused, match=reason):
        prove(head, base=base)


@pytest.mark.parametrize(
    ("head", "pypi", "reason"),
    [
        (tree(NEW, **{"uv.lock": lock(NEW, extra=lock_entry("left-pad", "1.0.0"))}), None, "more than the first-party"),
        (
            tree(NEW, **{"uv.lock": lock(NEW, lock_entry("posthoganalytics", NEW).replace('"requests"', '"evil"'))}),
            None,
            "more than the first-party",
        ),
        (
            tree(
                NEW,
                **{
                    "uv.lock": lock(
                        NEW, lock_entry("posthoganalytics", NEW).replace("pypi.org/simple", "evil.example.com")
                    )
                },
            ),
            None,
            "registry other than PyPI",
        ),
        (
            tree(NEW, **{"pyproject.toml": pyproject(NEW, extra="index-url = 'https://evil.example.com'\n")}),
            None,
            "adds or removes lines",
        ),
        (
            tree(NEW, **{"pyproject.toml": pyproject(NEW).replace(b'"7 days"', b'"0 days"')}),
            None,
            "not one first-party requirement",
        ),
        (tree("7.90.0"), None, "not an upgrade"),
        (tree("8.0.0"), None, "major change"),
        (tree(NEW, **{"tools/requirements.txt": requirements("7.91.3")}), None, "to different versions"),
        (
            tree(NEW, **{"uv.lock": lock(NEW, lock_entry("posthoganalytics", NEW, wheels=False))}),
            None,
            "every file PyPI serves",
        ),
        (
            tree(NEW, **{"uv.lock": lock(NEW).replace(digest(WHEEL).encode(), b"f" * 64)}),
            None,
            "hash for posthoganalytics-7.91.2-py3-none-any.whl",
        ),
        (
            tree(NEW),
            FakePyPI(
                **{
                    f"integrity/posthoganalytics/{NEW}/{WHEEL}/provenance": provenance(
                        WHEEL, {**PUBLISHER, "repository": "evil/fork"}
                    )
                }
            ),
            "was not published by PostHog/posthog-python",
        ),
        (
            tree(NEW),
            FakePyPI(
                **{f"integrity/posthoganalytics/{NEW}/{WHEEL}/provenance": provenance(WHEEL, subject="other.whl")}
            ),
            "attestation for another file",
        ),
        (
            tree(NEW),
            FakePyPI(**{f"pypi/posthoganalytics/{NEW}/json": release("posthoganalytics", NEW, ["requests", "evil"])}),
            "changes its requirements",
        ),
        (tree(NEW, **{"Dockerfile": b"FROM evil"}), None, "not a pyproject.toml"),
    ],
)
def test_a_bump_outside_the_first_party_shape_is_refused(
    head: dict[str, bytes], pypi: FakePyPI | None, reason: str
) -> None:
    with pytest.raises(Refused, match=reason):
        prove(head, pypi)
