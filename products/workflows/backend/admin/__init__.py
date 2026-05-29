# Importing these submodules fires their `@admin.register` decorators when
# `autodiscover_modules("admin")` imports this package.
from products.workflows.backend.admin import hog_flow_admin  # noqa: F401
