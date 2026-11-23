import re
import json
import base64
from collections.abc import Iterable, Iterator
from typing import Any

from .addresses import address
from .mappings import load_mapping
from .types import DiffError, EngineError, Identity, Json, ResourceDescription


def escape_template(value: str) -> str:
    return value.replace("${", "$${").replace("%{", "%%{")


def contains_secret(value: Json) -> bool:
    if isinstance(value, dict):
        return "$secret" in value or any(contains_secret(child) for child in value.values())
    return isinstance(value, list) and any(contains_secret(child) for child in value)


def definition_error(identity: Identity, path: str, message: str, code: str = "invalid_definition") -> EngineError:
    error: DiffError = {"code": code, "message": message, "kind": identity["kind"], "key": identity["key"]}
    if path:
        error["path"] = path
    return EngineError([error])


def field_values(body: dict[str, Json], paths: Iterable[str]) -> Iterator[tuple[str, Json]]:
    known = set(paths)

    def walk(value: dict[str, Json], prefix: str) -> Iterator[tuple[str, Json]]:
        for key, child in sorted(value.items()):
            path = f"{prefix}.{key}" if prefix else key
            if "." in key:
                # A literal dot in an API field name cannot denote a nested field.
                yield path + ".", child
            elif path not in known and any(field.startswith(path + ".") for field in known):
                if isinstance(child, dict):
                    yield from walk(child, path)
                elif child is not None:
                    yield path, child
            else:
                yield path, child

    yield from walk(body, "")


class BodyExpressions:
    def __init__(self, resource: ResourceDescription, definitions: set[tuple[str, str]], secrets: set[str]) -> None:
        self.resource = resource
        self.definitions = definitions
        self.secrets = secrets
        self.dependencies: set[tuple[str, str]] = set()

    def error(self, path: str, message: str, code: str = "invalid_definition") -> EngineError:
        return definition_error(self.resource, path, message, code)

    def reference(self, value: dict[str, Json], path: str) -> str | None:
        if "$secret" in value:
            name = value["$secret"]
            if len(value) != 1 or not isinstance(name, str) or not name.strip():
                raise self.error(path, "Use a named secret in this field and run check again.")
            self.secrets.add(name)
            if re.fullmatch(r"[A-Za-z0-9_./-]+", name):
                return f"var.stack_secrets[{json.dumps(name)}]"
            encoded = base64.b64encode(name.encode()).decode("ascii")
            return f'var.stack_secrets[base64decode("{encoded}")]'
        if "$ref" not in value:
            return None
        ref = value["$ref"]
        if len(value) != 1 or not isinstance(ref, dict) or ref.keys() - {"kind", "key", "attr"}:
            raise self.error(path, "Check the reference in this field.", "reference_missing")
        kind, key, attr = ref.get("kind"), ref.get("key"), ref.get("attr", "id")
        if not isinstance(kind, str) or not isinstance(key, str) or (kind, key) not in self.definitions:
            raise self.error(path, "Add the referenced definition or update this field.", "reference_missing")
        if attr == "id" or (attr == "short_id" and kind == "insight"):
            attribute = attr
        elif attr in ("name", "key", "path") and attr in load_mapping(kind)["fields"]:
            attribute = load_mapping(kind)["fields"][attr]
        else:
            raise self.error(path, "Choose an available field on the referenced definition.", "reference_missing")
        self.dependencies.add((kind, key))
        return f"{address(kind, key)}.{attribute}"

    def render(self, value: Json, path: str, *, as_json: bool = False) -> Any:
        if isinstance(value, dict):
            ref = self.reference(value, path)
            if ref is not None:
                # jsonencode supplies the JSON quoting after the assigned ID is known.
                return "${jsonencode(" + ref + ")}" if as_json else "${" + ref + "}"
            if as_json:
                return (
                    "{"
                    + ",".join(
                        escape_template(json.dumps(k)) + ":" + self.render(v, f"{path}.{k}", as_json=True)
                        for k, v in sorted(value.items())
                    )
                    + "}"
                )
            return {escape_template(k): self.render(v, f"{path}.{k}") for k, v in sorted(value.items())}
        if isinstance(value, list):
            items = [self.render(v, f"{path}[{i}]", as_json=as_json) for i, v in enumerate(value)]
            return "[" + ",".join(items) + "]" if as_json else items
        if as_json:
            return escape_template(json.dumps(value, allow_nan=False, ensure_ascii=False))
        return escape_template(value) if isinstance(value, str) else value
