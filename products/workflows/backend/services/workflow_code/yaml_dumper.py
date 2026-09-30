from typing import Any

import yaml

from products.workflows.backend.services.workflow_code.yaml_loader import CORE_SCHEMA_RESOLVERS


class _WorkflowDumper(yaml.SafeDumper):
    """PyYAML's safe dumper, quoting every string that YAML 1.1 or the YAML 1.2 core schema reads as another type.

    The safe dumper knows only YAML 1.1, so it would leave `0o12` plain, which the loader reads as a number.
    Sequences sit indented under their key, as people write them.
    """

    yaml_implicit_resolvers = {key: list(value) for key, value in yaml.SafeDumper.yaml_implicit_resolvers.items()}

    def increase_indent(self, flow: bool = False, indentless: bool = False) -> None:
        super().increase_indent(flow, False)


for _resolver in CORE_SCHEMA_RESOLVERS:
    _WorkflowDumper.add_implicit_resolver(_resolver.tag, _resolver.pattern, _resolver.first)


def _represent_str(dumper: yaml.SafeDumper, value: str) -> yaml.ScalarNode:
    style = "|" if "\n" in value else None
    return dumper.represent_scalar("tag:yaml.org,2002:str", value, style=style)


_WorkflowDumper.add_representer(str, _represent_str)


def dump_workflow_file(data: dict[str, Any], comments: list[str]) -> str:
    """The document as YAML, keys in the order given, with each comment as a # line on top."""
    body = yaml.dump(data, Dumper=_WorkflowDumper, sort_keys=False, allow_unicode=True, width=4096)
    header = "".join(f"# {line}\n" for comment in comments for line in comment.splitlines())
    return header + body
