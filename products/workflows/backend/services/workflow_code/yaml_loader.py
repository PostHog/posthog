import re
import json
import math
from typing import Any

import yaml
from yaml.events import AliasEvent
from yaml.nodes import MappingNode, Node, ScalarNode, SequenceNode

from posthog.dataclasses import frozen

from products.workflows.backend.facade.contracts import WorkflowCodeErrorStatus
from products.workflows.backend.services.workflow_code.errors import (
    DocumentError,
    DocumentInvalid,
    DocumentPath,
    PointsAt,
    Position,
    describe_path,
)

MAX_CONTENT_BYTES = 1024 * 1024
MAX_DEPTH = 100

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

    def compose_node(self, parent: Node | None, index: Any) -> Node | None:
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
    value_positions: dict[DocumentPath, Position]
    key_positions: dict[DocumentPath, Position]
    scalar_sources: dict[DocumentPath, str]

    def with_validation_errors(self, validation_errors: list[DocumentError]) -> list[DocumentError]:
        """The loader's errors plus the validation errors they do not already explain.

        A refused alias, tag or number leaves no usable value at its path, so a validation error under that
        path repeats the same mistake. A duplicate key keeps its first value, which is still checked.
        """
        refused = [
            error.path
            for error in self.errors
            if error.status != WorkflowCodeErrorStatus.DUPLICATE_KEY and error.path is not None
        ]
        return [
            *self.errors,
            *(
                error
                for error in validation_errors
                if error.path is None or not any(error.path[: len(path)] == path for path in refused)
            ),
        ]

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
    if content.lstrip().startswith("{"):
        return _load_json(content)
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
        errors=builder.errors,
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


def _position(mark: yaml.Mark) -> Position:
    return Position(line=mark.line + 1, column=mark.column + 1)


class _YamlBuilder:
    def __init__(self, loader: _CoreSchemaLoader) -> None:
        self.loader = loader
        self.errors: list[DocumentError] = []
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
            self._refuse_tag(self.loader.explicit_tags[id(node)], path)
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
            self.errors.append(_unstorable_number(path))
            return None
        if isinstance(value, float) and not math.isfinite(value):
            self.errors.append(_unstorable_number(path))
            return None
        return value

    def refuse_unused_anchors(self) -> None:
        for node_id, name in self.loader.anchor_names.items():
            if node_id not in self.loader.alias_uses and node_id not in self._refused_keys:
                path = self._first_paths.get(node_id)
                self.errors.append(
                    DocumentError(
                        status=WorkflowCodeErrorStatus.YAML_FEATURE_NOT_ALLOWED,
                        message=f"{describe_path(path)} sets the YAML anchor &{name}.",
                        why=_NO_ANCHORS,
                        fix=f"Remove &{name}.",
                        path=path,
                    )
                )

    def _build_alias(self, node: Node, path: DocumentPath) -> Any:
        use = self._alias_uses_seen.get(id(node), 0)
        self._alias_uses_seen[id(node)] = use + 1
        name, mark = self.loader.alias_uses[id(node)][use]
        self.value_positions[path] = _position(mark)
        self.errors.append(
            DocumentError(
                status=WorkflowCodeErrorStatus.YAML_FEATURE_NOT_ALLOWED,
                message=f"{describe_path(path)} uses the YAML alias *{name}.",
                why=_NO_ANCHORS,
                fix=f"Write the value out in full here, and remove the anchor &{name}.",
                path=path,
            )
        )
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
                shown = key_node.value if isinstance(key_node, ScalarNode) else "?"
                self._refuse_key((*path, shown), key_position, key_node)
                continue
            key: str = key_node.value
            child: DocumentPath = (*path, key)
            if key == "<<" and key_node.style is None:
                self._refuse_merge_key(child, key_position)
                continue
            if key in mapping:
                self.key_positions[child] = key_position
                self.errors.append(_duplicate_key(child))
                continue
            self.key_positions[child] = key_position
            mapping[key] = self.build(value_node, child)
        return mapping

    def _has_yaml_feature(self, node: Node) -> bool:
        return any(
            id(node) in used for used in (self.loader.anchor_names, self.loader.alias_uses, self.loader.explicit_tags)
        )

    def _refuse_key_feature(self, parent: DocumentPath, position: Position, key_node: Node) -> None:
        path: DocumentPath = (*parent, key_node.value if isinstance(key_node, ScalarNode) else "?")
        # Registered as seen, so a later alias of this key is refused as an alias and its anchor is not reported twice.
        self._first_paths.setdefault(id(key_node), path)
        self._refused_keys.add(id(key_node))
        self.key_positions[path] = position
        self.errors.append(
            DocumentError(
                status=WorkflowCodeErrorStatus.YAML_FEATURE_NOT_ALLOWED,
                message=f"{describe_path(parent)} has a key with a YAML anchor, alias or tag.",
                why=_NO_ANCHORS,
                fix="Write the key as plain text, without &, * or !.",
                path=path,
                points_at=PointsAt.KEY,
            )
        )

    def _refuse_key(self, path: DocumentPath, position: Position, key_node: Node) -> None:
        shown = key_node.value if isinstance(key_node, ScalarNode) else "a mapping or list"
        self.key_positions[path] = position
        self.errors.append(
            DocumentError(
                status=WorkflowCodeErrorStatus.YAML_FEATURE_NOT_ALLOWED,
                message=f"{describe_path(path[:-1])} has the key {shown}, which YAML does not read as text.",
                why="Every key in a workflow file is a field name, and a field name is text.",
                fix=f"Quote the key, for example '{shown}', or use the field name the schema gives.",
                path=path,
                points_at=PointsAt.KEY,
            )
        )

    def _refuse_merge_key(self, path: DocumentPath, position: Position) -> None:
        self.key_positions[path] = position
        self.errors.append(
            DocumentError(
                status=WorkflowCodeErrorStatus.YAML_FEATURE_NOT_ALLOWED,
                message=f"{describe_path(path[:-1])} uses the YAML merge key <<.",
                why="Workflow files do not use YAML merge keys, so each field is written where it applies and a diff shows every change.",
                fix="Write the merged fields out in full, and remove <<.",
                path=path,
                points_at=PointsAt.KEY,
            )
        )

    def _refuse_tag(self, tag: str, path: DocumentPath) -> None:
        self.errors.append(
            DocumentError(
                status=WorkflowCodeErrorStatus.YAML_FEATURE_NOT_ALLOWED,
                message=f"{describe_path(path)} has the YAML tag {tag}.",
                why="Workflow files do not use YAML tags. The schema already says which type each field takes.",
                fix="Remove the tag. If the value should be text, put it in quotes instead.",
                path=path,
            )
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
    errors: list[DocumentError] = []
    data = _build_json(raw, (), errors)
    return LoadedContent(data=data, errors=errors, value_positions={}, key_positions={}, scalar_sources={})


def _build_json(value: Any, path: DocumentPath, errors: list[DocumentError]) -> Any:
    if len(path) > MAX_DEPTH:
        raise DocumentInvalid([_too_deep(path)])
    if isinstance(value, _JsonObject):
        mapping: dict[str, Any] = {}
        for key, item in value:
            child: DocumentPath = (*path, key)
            if key in mapping:
                errors.append(_duplicate_key(child))
                continue
            mapping[key] = _build_json(item, child, errors)
        return mapping
    if isinstance(value, list):
        return [_build_json(item, (*path, index), errors) for index, item in enumerate(value)]
    if isinstance(value, float) and not math.isfinite(value):
        errors.append(_unstorable_number(path))
        return None
    return value


def _unstorable_number(path: DocumentPath | None) -> DocumentError:
    return DocumentError(
        status=WorkflowCodeErrorStatus.INVALID_VALUE,
        message=f"{describe_path(path)} holds a number PostHog cannot store: infinite, not a number, or too long to read.",
        why="A workflow is stored as JSON, which has no infinite or NaN numbers, and PostHog reads integers of up to 4300 digits.",
        fix="Use a finite number of normal length, or put the value in quotes to keep it as text.",
        path=path,
    )


def _duplicate_key(path: DocumentPath) -> DocumentError:
    return DocumentError(
        status=WorkflowCodeErrorStatus.DUPLICATE_KEY,
        message=f"{describe_path(path)} is set more than once.",
        why="A key can appear only once in a mapping. With two, it is not clear which value the workflow should use.",
        fix=f"Keep one {path[-1]} entry and remove the other.",
        path=path,
        points_at=PointsAt.KEY,
    )
