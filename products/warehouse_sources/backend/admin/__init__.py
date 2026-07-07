# Importing these submodules fires their `@admin.register` decorators when
# `autodiscover_modules("admin")` imports this package.
from products.warehouse_sources.backend.admin import (  # noqa: F401
    custom_oauth2_integration_admin,
    data_warehouse_table_admin,
    external_data_job_admin,
    external_data_schema_admin,
)
