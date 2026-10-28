"""Render `facade/kinds_generated.py`, the typed accessors of the integrations SDK, from `facade/catalogue.py`.

A renderer in the projection registry (`tools/hogli-commands/hogli_commands/projections.py`). Run
`hogli build:projections --only integration-kinds` after a change to the catalogue.

Each kind gets a class with one attribute per auth type that it supports, plus `any`. So mypy rejects
an auth type that a kind does not support, for example `IntegrationManager.github.credentials`.
"""

from products.integrations.backend.facade.catalogue import KINDS
from products.integrations.backend.facade.contracts import KindSpec
from products.integrations.backend.facade.enums import AuthType

OUTPUT = "products/integrations/backend/facade/kinds_generated.py"

HEADER = '''"""Generated from `products/integrations/backend/facade/catalogue.py`. Do not edit by hand.

Run `hogli build:projections --only integration-kinds` after a change to the catalogue. Import
`IntegrationManager` from `facade/api.py`, not the classes here.
"""

from enum import StrEnum

from products.integrations.backend.facade.api_accessors import (
    AuthAccessor,
    IntegrationManagerBase,
    IntegrationReader,
    KindAccessor,
)
from products.integrations.backend.facade.enums import AuthType
'''


def _attribute(kind: str) -> str:
    return kind.replace("-", "_")


def _class_name(kind: str) -> str:
    return "".join(part.capitalize() for part in kind.split("-")) + "Kind"


def _kind_class(kind: str, spec: KindSpec) -> list[str]:
    lines = ["", "", f"class {_class_name(kind)}(KindAccessor):", f'    kind = "{kind}"']
    for auth_type in AuthType:
        if auth_type not in spec.supported:
            continue
        note = "  # the default" if auth_type == spec.default else ""
        lines.append(f'    {auth_type.value} = AuthAccessor(kind="{kind}", auth_type=AuthType.{auth_type.name}){note}')
    lines.append(f'    any = IntegrationReader(kinds=frozenset({{"{kind}"}}))')
    return lines


def render_kinds() -> str:
    kinds = sorted(KINDS.items())
    # A plain StrEnum: the OpenAPI enum names come from the model's `Integration.IntegrationKind`, and a
    # second labeled class with the same name would make both names ambiguous.
    lines = [HEADER, "", "class IntegrationKind(StrEnum):"]
    lines += [f'    {_attribute(kind).upper()} = "{kind}"' for kind, _ in kinds]
    for kind, spec in kinds:
        lines += _kind_class(kind, spec)
    lines += ["", "", "class GeneratedIntegrationManager(IntegrationManagerBase):"]
    lines += [f"    {_attribute(kind)} = {_class_name(kind)}()" for kind, _ in kinds]
    return "\n".join(lines) + "\n"


def render() -> dict[str, str]:
    return {OUTPUT: render_kinds()}
