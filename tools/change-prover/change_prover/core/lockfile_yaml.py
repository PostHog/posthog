"""Reads pnpm's YAML files the way pnpm does, and refuses what two parsers could read differently."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

import yaml

from change_prover.core.policy import Refused

YAML_LOADER = getattr(yaml, "CSafeLoader", yaml.SafeLoader)


@dataclass(frozen=True)
class Unquoted:
    """A scalar that YAML reads as something other than a string, kept as the text in the file."""

    text: str

    def __str__(self) -> str:
        return self.text


class StrictLoader(YAML_LOADER):  # type: ignore[misc,valid-type]
    """Reads YAML without converting a scalar, and refuses what two parsers can read differently.

    The replay and the head lockfile are compared as the structures this loader builds, so it must
    not read two different texts as one structure. Type coercion would, because `1.10` and `1.1` are
    one float. Reading every scalar as a string would too, because pnpm reads `true` as a boolean and
    `"true"` as a string. So a string stays a `str`, a null stays `None`, and any other scalar becomes
    an `Unquoted` that holds its text. A repeated key is refused, because this parser keeps the last
    value and pnpm's may not. A scalar that spans lines is refused, because pnpm's parser joins the
    lines with other whitespace. pnpm writes one only for the `deprecated` note of a lockfile package,
    which `comparable` drops, so that one place is read.
    """

    def construct_document(self, node: yaml.Node) -> Any:
        pending: list[tuple[yaml.Node, tuple[Any, ...]]] = [(node, ())]
        while pending:
            child, path = pending.pop()
            if isinstance(child, yaml.MappingNode):
                for key, value in child.value:
                    pending += [(key, (*path, None)), (value, (*path, key.value))]
            elif isinstance(child, yaml.SequenceNode):
                pending += [(item, (*path, None)) for item in child.value]
            elif child.start_mark.line != child.end_mark.line and not (
                len(path) == 3 and path[0] == "packages" and path[2] == "deprecated"
            ):
                raise Refused("a YAML file spreads a scalar over lines")
        return super().construct_document(node)

    def construct_mapping(self, node: yaml.MappingNode, deep: bool = False) -> dict[Any, Any]:
        if not all(isinstance(key, yaml.ScalarNode) for key, _ in node.value):
            raise Refused("a YAML file uses a key that is not a scalar")
        keys = [self.construct_object(key, deep=deep) for key, _ in node.value]
        if len(set(keys)) != len(keys):
            raise Refused("a YAML file repeats a key")
        return super().construct_mapping(node, deep=deep)


for _tag in ("bool", "int", "float", "timestamp"):
    StrictLoader.add_constructor(f"tag:yaml.org,2002:{_tag}", lambda _loader, node: Unquoted(node.value))
# PyYAML resolves YAML 1.1. pnpm reads YAML 1.2, where a number needs neither a dot nor a sign on
# its exponent, and where `0o` starts an octal. This pattern also takes the `_` that js-yaml allows.
StrictLoader.add_implicit_resolver(
    "tag:yaml.org,2002:float",
    re.compile(r"^[-+]?(?:(?:[0-9][0-9_]*(?:\.[0-9_]*)?|\.[0-9_]+)(?:[eE][-+]?[0-9]+)?|0o[0-7_]+)$"),
    list("-+.0123456789"),
)


def load_yaml(text: bytes) -> dict[str, Any]:
    # pnpm reads UTF-8. PyYAML given bytes would detect UTF-16 and read it, so it is given text.
    try:
        decoded = text.decode("utf-8")
    except UnicodeDecodeError as error:
        raise Refused("a YAML file is not UTF-8") from error
    # PyYAML drops a byte order mark and ends a line at U+0085, U+2028 and U+2029. pnpm's parser does neither.
    if any(character in decoded for character in "\N{BYTE ORDER MARK}\x85\N{LINE SEPARATOR}\N{PARAGRAPH SEPARATOR}"):
        raise Refused("a YAML file uses a byte order mark or a line separator that pnpm does not read")
    # pnpm never writes an alias or an explicit tag, and either would let two texts build one
    # structure. The C parser skips a Python compose hook, so the event stream is read for them.
    try:
        for event in yaml.parse(decoded, Loader=StrictLoader):
            if isinstance(event, yaml.AliasEvent) or getattr(event, "tag", None) is not None:
                raise Refused("a YAML file uses an alias or an explicit tag")
            # pnpm takes a lockfile that opens with `---` for a metadata document with the lockfile after it.
            if getattr(event, "explicit", False):
                raise Refused("a YAML file uses a document marker")
        loaded = yaml.load(decoded, Loader=StrictLoader) or {}
    except yaml.YAMLError as error:
        raise Refused("a YAML file does not parse") from error
    if not isinstance(loaded, dict):
        raise Refused("a YAML file is not a mapping")
    return loaded


def comparable(lockfile: bytes) -> dict[str, Any]:
    """The lockfile as pnpm reads it, without the one field the registry sets after resolution.

    npm's `deprecated` metadata follows the registry, not the resolution, so a replay cannot reproduce
    it. Only a string under a `packages` entry is dropped, where pnpm writes it. Anywhere else it has
    to match the replay like every other key.
    """
    loaded = load_yaml(lockfile)
    for entry in (loaded.get("packages") or {}).values():
        if isinstance(entry, dict) and isinstance(entry.get("deprecated"), str):
            del entry["deprecated"]
    return loaded
