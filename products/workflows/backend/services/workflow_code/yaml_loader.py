import re
import json
import math
from collections.abc import Callable
from functools import partial
from typing import Any

import yaml
from yaml.events import AliasEvent
from yaml.nodes import MappingNode, Node, ScalarNode, SequenceNode

from posthog.dataclasses import frozen

from products.workflows.backend.facade.enums import WorkflowCodeErrorStatus
from products.workflows.backend.services.workflow_code.errors import (
    DocumentError,
    DocumentInvalid,
    DocumentPath,
    ErrorCollector,
    PointsAt,
    Position,
    describe_path,
    shortened,
    shown,
)

MAX_CONTENT_BYTES = 1024 * 1024
MAX_DEPTH = 100
# Parsing costs time per value, so this bounds the work one request can ask for.
MAX_VALUES = 100_000

_UNSTORABLE_CHARACTERS = re.compile(r"[\x00\ud800-\udfff]")

_NO_ANCHORS = "Workflow files do not use YAML anchors and aliases, so each value is written where it is used and a diff shows every change."

_STR_TAG = "tag:yaml.org,2002:str"
_NULL_TAG = "tag:yaml.org,2002:null"
_BOOL_TAG = "tag:yaml.org,2002:bool"
_INT_TAG = "tag:yaml.org,2002:int"
_FLOAT_TAG = "tag:yaml.org,2002:float"


class _CoreSchemaLoader(yaml.SafeLoader):
    """PyYAML with the YAML 1.2 core schema's implicit types in place of YAML 1.1's.

    YAML 1.1 reads `on`, `no` and `yes` as booleans, `1:30` as the sexagesimal 90 and `2026-09-30` as
    a date. Workflow files are YAML 1.2, so those stay text. The loader also records anchors, aliases
    and explicit tags while it composes, because the node tree it returns no longer carries them.
    """

    yaml_implicit_resolvers: dict = {}

    def __init__(self, stream: str) -> None:
        super().__init__(stream)
        self.anchor_names: dict[int, str] = {}
        self.alias_uses: dict[int, list[tuple[str, yaml.Mark]]] = {}
        self.explicit_tags: dict[int, str] = {}
        self.values_composed = 0

    def compose_node(self, parent: Node | None, index: Any) -> Node | None:
        self.values_composed += 1
        if self.values_composed > MAX_VALUES:
            raise DocumentInvalid([_too_many_values()])
        event = self.peek_event()
        node = super().compose_node(parent, index)
        if isinstance(event, AliasEvent):
            self.alias_uses.setdefault(id(node), []).append((event.anchor, event.start_mark))
            return node
        if event.anchor is not None:
            self.anchor_names[id(node)] = event.anchor
        if event.tag is not None:
            self.explicit_tags[id(node)] = event.tag
        return node


@frozen
class ImplicitResolver:
    tag: str
    pattern: re.Pattern[str]
    first: tuple[str, ...]


CORE_SCHEMA_RESOLVERS = (
    ImplicitResolver(tag=_BOOL_TAG, pattern=re.compile(r"^(?:true|True|TRUE|false|False|FALSE)$"), first=tuple("tTfF")),
    ImplicitResolver(tag=_NULL_TAG, pattern=re.compile(r"^(?:~|null|Null|NULL|)$"), first=("~", "n", "N", "")),
    ImplicitResolver(
        tag=_INT_TAG, pattern=re.compile(r"^(?:[-+]?[0-9]+|0o[0-7]+|0x[0-9a-fA-F]+)$"), first=tuple("-+0123456789")
    ),
    ImplicitResolver(
        tag=_FLOAT_TAG,
        pattern=re.compile(
            r"^(?:[-+]?(?:\.[0-9]+|[0-9]+(?:\.[0-9]*)?)(?:[eE][-+]?[0-9]+)?|[-+]?\.(?:inf|Inf|INF)|\.(?:nan|NaN|NAN))$"
        ),
        first=tuple("-+0123456789."),
    ),
)
"""The YAML 1.2 core schema's implicit types."""

for _resolver in CORE_SCHEMA_RESOLVERS:
    _CoreSchemaLoader.add_implicit_resolver(_resolver.tag, _resolver.pattern, list(_resolver.first))


@frozen
class LoadedContent:
    data: Any
    errors: list[DocumentError]
    errors_left_out: int
    refused_paths: frozenset[DocumentPath]
    """Paths the loader refused a value at. A duplicate key keeps its first value, which is still checked."""
    value_positions: dict[DocumentPath, Position]
    key_positions: dict[DocumentPath, Position]
    scalar_sources: dict[DocumentPath, str]

    def locate(self, error: DocumentError) -> Position | None:
        if error.position is not None:
            return error.position
        if error.path is None:
            return None
        if error.points_at == PointsAt.KEY and error.path in self.key_positions:
            return self.key_positions[error.path]
        path = error.path[:-1] if error.points_at == PointsAt.PARENT else error.path
        while True:
            if path in self.value_positions:
                return self.value_positions[path]
            if not path:
                return None
            path = path[:-1]


def load_content(content: str) -> LoadedContent:
    size = len(content.encode("utf-8"))
    if size > MAX_CONTENT_BYTES:
        raise DocumentInvalid(
            [
                DocumentError(
                    status=WorkflowCodeErrorStatus.CONTENT_TOO_LARGE,
                    message=f"The content is {size} bytes, which is over the limit of {MAX_CONTENT_BYTES} bytes.",
                    why="PostHog checks one workflow file per request, and a workflow file is far smaller than this.",
                    fix="Send one workflow file per request, and remove anything that is not part of the workflow.",
                    path=None,
                )
            ]
        )
    if content.lstrip("﻿ \t\r\n").startswith("{"):
        return _load_json(content.lstrip("﻿"))
    return _load_yaml(content)


def _load_yaml(content: str) -> LoadedContent:
    try:
        loader = _CoreSchemaLoader(content)
    except yaml.YAMLError as error:
        raise DocumentInvalid([_yaml_syntax_error(str(error), None)])
    try:
        root = loader.get_single_node()
    except yaml.MarkedYAMLError as error:
        mark = error.problem_mark or error.context_mark
        raise DocumentInvalid([_yaml_syntax_error(str(error.problem or error.context), mark)])
    except yaml.YAMLError as error:
        raise DocumentInvalid([_yaml_syntax_error(str(error), None)])
    except RecursionError:
        raise DocumentInvalid([_too_deep(None)])
    finally:
        loader.dispose()
    builder = _YamlBuilder(loader)
    data = builder.build(root, ()) if root is not None else None
    builder.refuse_unused_anchors()
    return LoadedContent(
        data=data,
        errors=builder.collector.errors,
        errors_left_out=builder.collector.left_out,
        refused_paths=frozenset(builder.refused_paths),
        value_positions=builder.value_positions,
        key_positions=builder.key_positions,
        scalar_sources=builder.scalar_sources,
    )


def _yaml_syntax_error(problem: str, mark: yaml.Mark | None) -> DocumentError:
    return DocumentError(
        status=WorkflowCodeErrorStatus.INVALID_YAML,
        message=f"The file is not valid YAML: {problem}.",
        why="PostHog reads the file as YAML before it checks the workflow, and the YAML parser stopped here.",
        fix="Fix the YAML at this point. Check the indentation, the quotes and the colons, and remove control characters.",
        path=None,
        position=_position(mark) if mark is not None else None,
    )


def _too_deep(path: DocumentPath | None) -> DocumentError:
    return DocumentError(
        status=WorkflowCodeErrorStatus.INVALID_YAML,
        message=f"The content nests more than {MAX_DEPTH} levels deep.",
        why="A workflow file nests a few levels for each branch. Content this deep is not a workflow, and PostHog stops reading it.",
        fix="Remove the deeply nested part, or move deep branches into steps of their own.",
        path=path,
    )


def _too_many_values() -> DocumentError:
    return DocumentError(
        status=WorkflowCodeErrorStatus.CONTENT_TOO_LARGE,
        message=f"The content holds more than {MAX_VALUES} values.",
        why="PostHog checks one workflow file per request, and a workflow file holds far fewer values than this.",
        fix="Send one workflow file per request, and remove anything that is not part of the workflow.",
        path=None,
    )


def _position(mark: yaml.Mark) -> Position:
    return Position(line=mark.line + 1, column=mark.column + 1)


class _Refusals:
    """The errors a builder finds, and the paths where it refused a value."""

    def __init__(self) -> None:
        self.collector = ErrorCollector()
        self.refused_paths: set[DocumentPath] = set()

    def refuse(self, path: DocumentPath | None, describe: Callable[[], DocumentError]) -> None:
        if path is not None:
            self.refused_paths.add(path)
        self.collector.add(describe)


class _YamlBuilder(_Refusals):
    def __init__(self, loader: _CoreSchemaLoader) -> None:
        super().__init__()
        self.loader = loader
        self.value_positions: dict[DocumentPath, Position] = {}
        self.key_positions: dict[DocumentPath, Position] = {}
        self.scalar_sources: dict[DocumentPath, str] = {}
        self._first_paths: dict[int, DocumentPath] = {}
        self._alias_uses_seen: dict[int, int] = {}
        self._refused_keys: set[int] = set()

    def build(self, node: Node, path: DocumentPath) -> Any:
        if id(node) in self._first_paths:
            return self._build_alias(node, path)
        if len(path) > MAX_DEPTH:
            raise DocumentInvalid([_too_deep(path)])
        self._first_paths[id(node)] = path
        self.value_positions[path] = _position(node.start_mark)
        if id(node) in self.loader.explicit_tags:
            tag = self.loader.explicit_tags[id(node)]
            self.refuse(path, lambda: _tag_not_allowed(tag, path))
        if isinstance(node, MappingNode):
            value: Any = self._build_mapping(node, path)
        elif isinstance(node, SequenceNode):
            value = [self.build(item, (*path, index)) for index, item in enumerate(node.value)]
        else:
            assert isinstance(node, ScalarNode)
            if node.style is None:
                self.scalar_sources[path] = node.value
            value = self._scalar(node, path)
        return value

    def _scalar(self, node: ScalarNode, path: DocumentPath) -> Any:
        try:
            value = _scalar_value(node)
        except ValueError:
            # Python refuses to read an integer of more than 4300 digits.
            self.refuse(path, lambda: _unstorable_number(path))
            return None
        if isinstance(value, float) and not math.isfinite(value):
            self.refuse(path, lambda: _unstorable_number(path))
            return None
        if isinstance(value, str) and _UNSTORABLE_CHARACTERS.search(value):
            self.refuse(path, lambda: _unstorable_text(path))
            return None
        if isinstance(value, int | float) and not isinstance(value, bool) and node.value not in _number_texts(value):
            self.refuse(path, lambda: _number_not_as_written(path, node.value, value))
            return None
        return value

    def refuse_unused_anchors(self) -> None:
        for node_id, name in self.loader.anchor_names.items():
            if node_id not in self.loader.alias_uses and node_id not in self._refused_keys:
                path = self._first_paths.get(node_id)
                self.refuse(path, partial(_anchor_not_allowed, name, path))

    def _build_alias(self, node: Node, path: DocumentPath) -> Any:
        use = self._alias_uses_seen.get(id(node), 0)
        self._alias_uses_seen[id(node)] = use + 1
        name, mark = self.loader.alias_uses[id(node)][use]
        self.value_positions[path] = _position(mark)
        self.refuse(path, lambda: _alias_not_allowed(name, path))
        # The aliased value is not expanded: a chain of aliases can double in size at every level, and an
        # alias can point at its own ancestor. Validation skips this path because the alias is the error.
        return None

    def _build_mapping(self, node: MappingNode, path: DocumentPath) -> dict[str, Any]:
        mapping: dict[str, Any] = {}
        for key_node, value_node in node.value:
            key_position = _position(key_node.start_mark)
            if self._has_yaml_feature(key_node):
                self._refuse_key_feature(path, key_position, key_node)
                continue
            if not isinstance(key_node, ScalarNode) or key_node.tag != _STR_TAG:
                self._refuse_key(path, key_position, key_node)
                continue
            key: str = key_node.value
            if _UNSTORABLE_CHARACTERS.search(key):
                self._refuse_unstorable_key(path, key, key_position)
                continue
            child: DocumentPath = (*path, key)
            if key == "<<" and key_node.style is None:
                self._refuse_merge_key(child, key_position)
                continue
            if key in mapping:
                self.key_positions[child] = key_position
                self.collector.add(partial(_duplicate_key, child))
                continue
            self.key_positions[child] = key_position
            mapping[key] = self.build(value_node, child)
        return mapping

    def _has_yaml_feature(self, node: Node) -> bool:
        return any(
            id(node) in used for used in (self.loader.anchor_names, self.loader.alias_uses, self.loader.explicit_tags)
        )

    def _refuse_key_feature(self, parent: DocumentPath, position: Position, key_node: Node) -> None:
        path: DocumentPath = (*parent, _key_text(key_node))
        # Registered as seen, so a later alias of this key is refused as an alias and its anchor is not reported twice.
        self._first_paths.setdefault(id(key_node), path)
        self._refused_keys.add(id(key_node))
        self.key_positions[path] = position
        self.refuse(path, lambda: _key_feature_not_allowed(parent, path))

    def _refuse_key(self, parent: DocumentPath, position: Position, key_node: Node) -> None:
        path: DocumentPath = (*parent, _key_text(key_node))
        self.key_positions[path] = position
        self.refuse(path, lambda: _key_not_text(path, key_node))

    def _refuse_unstorable_key(self, parent: DocumentPath, key: str, position: Position) -> None:
        path: DocumentPath = (*parent, _storable(key))
        self.key_positions[path] = position
        self.refuse(path, lambda: _unstorable_text(path, points_at=PointsAt.KEY))

    def _refuse_merge_key(self, path: DocumentPath, position: Position) -> None:
        self.key_positions[path] = position
        self.refuse(path, lambda: _merge_key_not_allowed(path))


def _key_text(key_node: Node) -> str:
    return _storable(key_node.value) if isinstance(key_node, ScalarNode) else "?"


def _tag_not_allowed(tag: str, path: DocumentPath) -> DocumentError:
    return DocumentError(
        status=WorkflowCodeErrorStatus.YAML_FEATURE_NOT_ALLOWED,
        message=f"{describe_path(path)} has the YAML tag {shortened(_storable(tag))}.",
        why="Workflow files do not use YAML tags. The schema already says which type each field takes.",
        fix="Remove the tag. If the value should be text, put it in quotes instead.",
        path=path,
    )


def _anchor_not_allowed(name: str, path: DocumentPath | None) -> DocumentError:
    return DocumentError(
        status=WorkflowCodeErrorStatus.YAML_FEATURE_NOT_ALLOWED,
        message=f"{describe_path(path)} sets the YAML anchor &{shortened(name)}.",
        why=_NO_ANCHORS,
        fix=f"Remove &{shortened(name)}.",
        path=path,
    )


def _alias_not_allowed(name: str, path: DocumentPath) -> DocumentError:
    return DocumentError(
        status=WorkflowCodeErrorStatus.YAML_FEATURE_NOT_ALLOWED,
        message=f"{describe_path(path)} uses the YAML alias *{shortened(name)}.",
        why=_NO_ANCHORS,
        fix=f"Write the value out in full here, and remove the anchor &{shortened(name)}.",
        path=path,
    )


def _key_feature_not_allowed(parent: DocumentPath, path: DocumentPath) -> DocumentError:
    return DocumentError(
        status=WorkflowCodeErrorStatus.YAML_FEATURE_NOT_ALLOWED,
        message=f"{describe_path(parent)} has a key with a YAML anchor, alias or tag.",
        why=_NO_ANCHORS,
        fix="Write the key as plain text, without &, * or !.",
        path=path,
        points_at=PointsAt.KEY,
    )


def _key_not_text(path: DocumentPath, key_node: Node) -> DocumentError:
    key = shortened(_key_text(key_node)) if isinstance(key_node, ScalarNode) else "a mapping or list"
    return DocumentError(
        status=WorkflowCodeErrorStatus.YAML_FEATURE_NOT_ALLOWED,
        message=f"{describe_path(path[:-1])} has the key {key}, which YAML does not read as text.",
        why="Every key in a workflow file is a field name, and a field name is text.",
        fix=f"Quote the key, for example '{key}', or use the field name the schema gives.",
        path=path,
        points_at=PointsAt.KEY,
    )


def _merge_key_not_allowed(path: DocumentPath) -> DocumentError:
    return DocumentError(
        status=WorkflowCodeErrorStatus.YAML_FEATURE_NOT_ALLOWED,
        message=f"{describe_path(path[:-1])} uses the YAML merge key <<.",
        why="Workflow files do not use YAML merge keys, so each field is written where it applies and a diff shows every change.",
        fix="Write the merged fields out in full, and remove <<.",
        path=path,
        points_at=PointsAt.KEY,
    )


def _scalar_value(node: ScalarNode) -> Any:
    text = node.value
    if node.tag == _NULL_TAG:
        return None
    if node.tag == _BOOL_TAG:
        return text in ("true", "True", "TRUE")
    if node.tag == _INT_TAG:
        if text.startswith("0o"):
            return int(text[2:], 8)
        if text.startswith("0x"):
            return int(text[2:], 16)
        return int(text)
    if node.tag == _FLOAT_TAG:
        unsigned = text.lstrip("+-").lower()
        if unsigned in (".inf", ".nan"):
            return float(text.replace(".", "", 1))
        return float(text)
    return text


class _JsonObject(list):
    pass


def _load_json(content: str) -> LoadedContent:
    try:
        raw = json.loads(content, object_pairs_hook=_JsonObject)
    except json.JSONDecodeError as error:
        raise DocumentInvalid(
            [
                DocumentError(
                    status=WorkflowCodeErrorStatus.INVALID_YAML,
                    message=f"The content is not valid JSON at line {error.lineno}, column {error.colno}: {error.msg}.",
                    why="Content that starts with { is read as JSON, not YAML, and the JSON parser stopped here.",
                    fix="Fix the JSON at this point, or send the file as YAML.",
                    path=None,
                )
            ]
        )
    except RecursionError:
        raise DocumentInvalid([_too_deep(None)])
    except ValueError:
        # Python refuses to read an integer of more than 4300 digits, and json.loads says no more than that.
        raise DocumentInvalid([_unstorable_number(None)])
    builder = _JsonBuilder()
    data = builder.build(raw, ())
    return LoadedContent(
        data=data,
        errors=builder.collector.errors,
        errors_left_out=builder.collector.left_out,
        refused_paths=frozenset(builder.refused_paths),
        value_positions={},
        key_positions={},
        scalar_sources={},
    )


class _JsonBuilder(_Refusals):
    def __init__(self) -> None:
        super().__init__()
        self._values_built = 0

    def build(self, value: Any, path: DocumentPath) -> Any:
        self._count(1)
        if len(path) > MAX_DEPTH:
            raise DocumentInvalid([_too_deep(path)])
        if isinstance(value, _JsonObject):
            return self._build_object(value, path)
        if isinstance(value, list):
            return [self.build(item, (*path, index)) for index, item in enumerate(value)]
        if isinstance(value, float) and not math.isfinite(value):
            self.refuse(path, lambda: _unstorable_number(path))
            return None
        if isinstance(value, str) and _UNSTORABLE_CHARACTERS.search(value):
            self.refuse(path, lambda: _unstorable_text(path))
            return None
        return value

    def _count(self, values: int) -> None:
        # Counted as the YAML loader counts them, keys included.
        self._values_built += values
        if self._values_built > MAX_VALUES:
            raise DocumentInvalid([_too_many_values()])

    def _build_object(self, pairs: _JsonObject, path: DocumentPath) -> dict[str, Any]:
        self._count(len(pairs))
        mapping: dict[str, Any] = {}
        for key, item in pairs:
            if _UNSTORABLE_CHARACTERS.search(key):
                bad: DocumentPath = (*path, _storable(key))
                self.refuse(bad, partial(_unstorable_text, bad, points_at=PointsAt.KEY))
                continue
            child: DocumentPath = (*path, key)
            if key in mapping:
                self.collector.add(partial(_duplicate_key, child))
                continue
            mapping[key] = self.build(item, child)
        return mapping


def _unstorable_number(path: DocumentPath | None) -> DocumentError:
    return DocumentError(
        status=WorkflowCodeErrorStatus.INVALID_VALUE,
        message=f"{describe_path(path)} holds a number PostHog cannot store: infinite, not a number, or too long to read.",
        why="A workflow is stored as JSON, which has no infinite or NaN numbers, and PostHog reads integers of up to 4300 digits.",
        fix="Use a finite number of normal length, or put the value in quotes to keep it as text.",
        path=path,
    )


def _storable(text: str) -> str:
    return _UNSTORABLE_CHARACTERS.sub("�", text)


def _unstorable_text(path: DocumentPath, points_at: PointsAt = PointsAt.VALUE) -> DocumentError:
    return DocumentError(
        status=WorkflowCodeErrorStatus.INVALID_VALUE,
        message=f"{describe_path(path)} holds a NUL character or half of a surrogate pair, which PostHog cannot store.",
        why="PostHog stores a workflow as JSON in Postgres, which refuses NUL, and half of a surrogate pair is not a character on its own.",
        fix="Remove the NUL character (\\0 or \\u0000) and any \\u escape from \\ud800 to \\udfff that has no other half. In YAML, write a character such as an emoji as itself, or as one \\U escape, for example \\U0001F600.",
        path=path,
        points_at=points_at,
    )


def _number_texts(value: int | float) -> tuple[str, ...]:
    """The ways to write a number that keep the text as written: Python's own, and the one a pull writes."""
    if isinstance(value, int):
        return (str(value),)
    written = repr(value)
    return (written, _dumped_float(written))


def _dumped_float(written: str) -> str:
    # PyYAML's representer adds .0 to an exponent without a decimal point, as in 1.0e-07.
    return written.replace("e", ".0e", 1) if "." not in written and "e" in written else written


def _number_not_as_written(path: DocumentPath, source: str, value: int | float) -> DocumentError:
    number = shortened(_number_texts(value)[-1])
    return DocumentError(
        status=WorkflowCodeErrorStatus.INVALID_VALUE,
        message=f"{describe_path(path)} is {shortened(source)}, which YAML reads as the number {number}.",
        why="A number keeps only its value, so 1.10 is stored as 1.1 and 012 as 12. A condition that compares it with text such as '1.10' never matches, and some YAML editors read the same value as another number.",
        fix=f"Write {number} to keep the number, or put the value in quotes, {shown(source)}, to keep it as text.",
        path=path,
    )


def _duplicate_key(path: DocumentPath) -> DocumentError:
    return DocumentError(
        status=WorkflowCodeErrorStatus.DUPLICATE_KEY,
        message=f"{describe_path(path)} is set more than once.",
        why="A key can appear only once in a mapping. With two, it is not clear which value the workflow should use.",
        fix=f"Keep one {shortened(str(path[-1]))} entry and remove the other.",
        path=path,
        points_at=PointsAt.KEY,
    )
