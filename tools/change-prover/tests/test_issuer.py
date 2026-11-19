import pytest

from change_prover.core import issuer
from change_prover.core.issuer import InvalidIssuerManifest

OWN = "tools/change-prover/issuer.yml"


@pytest.mark.parametrize(
    ("text", "expected", "reason"),
    [
        (b"paths:\n  - tools/change-prover/\n  - .nvmrc\n", ("tools/change-prover/", ".nvmrc"), None),
        (b"paths:\n  - tools/change-prover/issuer.yml\n", ("tools/change-prover/issuer.yml",), None),
        (b"paths:\n  - .nvmrc\n", None, "does not cover itself"),
        (b"paths:\n  - tools/\n  - tools/\n", None, "twice"),
        (b"paths: []\n", None, "non-empty list"),
        (b"paths:\n  - tools/\nother: 1\n", None, "single key"),
        (b"paths:\n  - tools/\n  - 3\n", None, "not a non-empty string"),
        (b"paths:\n  - tools/\n  - ../secrets\n", None, "not a plain repo-relative path"),
        (b"paths:\n  - tools/\n  - /etc/passwd\n", None, "not a plain repo-relative path"),
        (b"paths:\n  - tools/\n  - a//b\n", None, "not a plain repo-relative path"),
        (b"paths:\n  - tools/\n  - '*.yml'\n", None, "glob character"),
        (b"paths:\n  - tools/\n" + b"".join(b"  - f%d\n" % i for i in range(32)), None, "more than 32"),
        (b"# " + b"x" * issuer.MAX_BYTES + b"\npaths:\n  - tools/\n", None, "larger than"),
        (b"paths:\n  - tools/\npaths:\n  - .nvmrc\n", None, "does not parse"),
    ],
)
def test_parse_manifest(text: bytes, expected: tuple[str, ...] | None, reason: str | None) -> None:
    if reason is None:
        assert issuer.parse_manifest(text, OWN) == expected
    else:
        with pytest.raises(InvalidIssuerManifest, match=reason):
            issuer.parse_manifest(text, OWN)
