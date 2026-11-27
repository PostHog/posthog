"""Render the frozen credential kinds, the default auth types and the field classification audit.

A renderer in the projection registry (`tools/hogli-commands/hogli_commands/projections.py`). Run
`hogli build:projections --only warehouse-source-fields` after adding or changing a source. A changed
kind or default auth type of an existing source fails the render, because integration rows store these
values. Write such a change with `python manage.py generate_source_field_classification --allow-changed-defaults`.
"""

from pathlib import Path

from products.warehouse_sources.backend.temporal.data_imports.sources.common.credential_auth_type import (
    CREDENTIAL_AUTH_TYPES_PATH,
    render_credential_auth_types,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.credential_kind import (
    CREDENTIAL_KINDS_PATH,
    render_credential_kinds,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.job_input_classification import (
    CLASSIFICATION_AUDIT_PATH,
    render_classification_audit,
)

REPO_ROOT = Path(__file__).resolve().parents[7]


def render() -> dict[str, str]:
    return {
        str(CREDENTIAL_KINDS_PATH.relative_to(REPO_ROOT)): render_credential_kinds(),
        str(CREDENTIAL_AUTH_TYPES_PATH.relative_to(REPO_ROOT)): render_credential_auth_types(),
        str(CLASSIFICATION_AUDIT_PATH.relative_to(REPO_ROOT)): render_classification_audit(),
    }
