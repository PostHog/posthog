"""Render the frozen credential kinds, the default auth types and the field classification audit.

A renderer in the projection registry (`tools/hogli-commands/hogli_commands/projections.py`). Run
`hogli build:projections --only warehouse-source-fields` after adding or changing a source. A changed
kind or default auth type of an existing source fails the render, because integration rows store these
values. Write such a change with `python manage.py generate_source_field_classification --allow-changed-defaults`.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.credential_auth_type import (
    render_credential_auth_types,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.credential_kind import (
    render_credential_kinds,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.job_input_classification import (
    render_classification_audit,
)

CREDENTIAL_KINDS = "products/warehouse_sources/backend/facade/credential_kinds.py"
CREDENTIAL_AUTH_TYPES = "products/warehouse_sources/backend/facade/credential_auth_types.py"
CLASSIFICATION_AUDIT = "products/warehouse_sources/backend/temporal/data_imports/sources/field_classification.csv"


def render() -> dict[str, str]:
    return {
        CREDENTIAL_KINDS: render_credential_kinds(),
        CREDENTIAL_AUTH_TYPES: render_credential_auth_types(),
        CLASSIFICATION_AUDIT: render_classification_audit(),
    }
