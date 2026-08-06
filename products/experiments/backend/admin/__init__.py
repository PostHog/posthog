# Importing these submodules fires their `@admin.register` decorators when
# `autodiscover_modules("admin")` imports this package.
from products.experiments.backend.admin import (  # noqa: F401
    experiment_admin,
    experiment_saved_metric_admin,
    recalculation_admin,
)
