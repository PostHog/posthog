# Importing these submodules fires their `@admin.register` decorators when
# `autodiscover_modules("admin")` imports this package.
from products.workflows.backend.admin import (  # noqa: F401
    hog_flow_admin,
    hog_flow_batch_job_admin,
    hog_flow_template_admin,
)
