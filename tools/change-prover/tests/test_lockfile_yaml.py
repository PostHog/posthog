import pytest

from change_prover.core.lockfile_yaml import comparable
from change_prover.core.policy import Refused


def lockfile(
    name: str,
    specifier: str,
    version: str,
    integrity: str = "sha512-x",
    deprecated: bool = False,
    catalog: str | None = None,
) -> bytes:
    deprecation = "    deprecated: |-\n      use something else,\n      see the notes\n" if deprecated else ""
    snapshot = (
        f"catalogs:\n  default:\n    {name}:\n      specifier: {catalog}\n      version: {version}\n\n"
        if catalog
        else ""
    )
    return (
        f"lockfileVersion: '9.0'\n\n{snapshot}importers:\n\n  .:\n    dependencies:\n      {name}:\n        specifier: '{specifier}'\n"
        f"        version: {version}\n\npackages:\n\n  {name}@{version}:\n    resolution: {{integrity: {integrity}}}\n"
        f"{deprecation}\nsnapshots:\n\n  {name}@{version}: {{}}\n"
    ).encode()


def test_comparable_ignores_only_a_deprecation_under_a_package() -> None:
    plain, deprecated = (
        lockfile("left-pad", "^1.3.1", "1.3.1"),
        lockfile("left-pad", "^1.3.1", "1.3.1", deprecated=True),
    )
    assert comparable(plain) == comparable(deprecated)
    assert comparable(plain) != comparable(lockfile("left-pad", "^1.3.1", "1.3.2"))
    elsewhere = plain.replace(b"        version: 1.3.1\n", b"        version: 1.3.1\n        deprecated: x\n")
    assert comparable(plain) != comparable(elsewhere)


@pytest.mark.parametrize(
    ("one", "other", "same"),
    [
        (b"a: 1.10\n", b"a: 1.1\n", False),
        (b"a: true\n", b'a: "true"\n', False),
        (b"a: 1e3\n", b"a: '1e3'\n", False),
        (b"a: 1.5e3\n", b"a: '1.5e3'\n", False),
        (b"a: .5e3\n", b"a: '.5e3'\n", False),
        (b"a: 0o17\n", b"a: '0o17'\n", False),
        (b"a: ~\n", b"a: 'null'\n", False),
        (b"a: ~\n", b"a: null\n", True),
        (b"a: '1.0'\n", b'a: "1.0"\n', True),
        (b"a: left-pad\n", b"a: 'left-pad'\n", True),
    ],
)
def test_comparable_keeps_scalars_that_pnpm_reads_differently_apart(one: bytes, other: bytes, same: bool) -> None:
    assert (comparable(one) == comparable(other)) is same


@pytest.mark.parametrize(
    ("text", "reason"),
    [
        (b"a: 1\na: 2\n", "repeats a key"),
        (b"? [a]\n: 1\n", "a key that is not a scalar"),
        (b'a: [deprecated, "b \n  c"]\n', "spreads a scalar over lines"),
        (b"packages:\n  a@1.0.0:\n    engines: |\n      node\n", "spreads a scalar over lines"),
        (b"snapshots:\n  a@1.0.0:\n    deprecated: |\n      b\n", "spreads a scalar over lines"),
        (b"packages:\n  a@1.0.0:\n    deprecated:\n      b: |\n        c\n", "spreads a scalar over lines"),
        (b"packages:\n  a@1.0.0:\n    deprecated:\n      ? |\n        b\n      : c\n", "spreads a scalar over lines"),
        (b"- packages:\n    a@1.0.0:\n      deprecated: |\n        b\n", "spreads a scalar over lines"),
        (b"a: [1\n", "does not parse"),
        (b"a: &x 1\nb: *x\n", "an alias or an explicit tag"),
        (b"hasBin: !!int true\n", "an alias or an explicit tag"),
        (b"a: !!map {}\n", "an alias or an explicit tag"),
        (b"---\na: 1\n", "a document marker"),
        ("a: 1\N{LINE SEPARATOR}b: 2\n".encode(), "a line separator"),
        ("a: 1\x85b: 2\n".encode(), "a line separator"),
        ("a: 1\n".encode("utf-16"), "not UTF-8"),
        ("a: 1\n".encode("utf-8-sig"), "a byte order mark"),
    ],
)
def test_comparable_refuses_yaml_that_pnpm_never_writes(text: bytes, reason: str) -> None:
    with pytest.raises(Refused, match=reason):
        comparable(text)
