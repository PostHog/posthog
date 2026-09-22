from posthog.models.activity_logging.utils import CreatedByInfo

from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource


def get_external_data_source_detail_name(external_data_source: ExternalDataSource) -> str:
    """Generate detail name for ExternalDataSource activity"""
    source_type = external_data_source.source_type or "unknown"

    if external_data_source.prefix:
        return f"{source_type} ({external_data_source.prefix})"

    return source_type


def get_external_data_source_created_by_info(
    external_data_source: ExternalDataSource,
) -> CreatedByInfo:
    """Get created by user information from ExternalDataSource"""
    created_by_user_id = None
    created_by_user_email = None
    created_by_user_name = None

    if hasattr(external_data_source, "created_by") and external_data_source.created_by:
        created_by_user_id = str(external_data_source.created_by.id)
        created_by_user_email = external_data_source.created_by.email
        created_by_user_name = (
            f"{external_data_source.created_by.first_name} {external_data_source.created_by.last_name}".strip()
        )

    return CreatedByInfo(user_id=created_by_user_id, email=created_by_user_email, name=created_by_user_name)
