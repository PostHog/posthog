"""The in-sandbox SQLV2 kernel-server, as a real package.

Nothing here may import Django or posthog. This code runs in the notebook sandbox
as the `nb_kernel` package (`python -m nb_kernel.server`), reaching it either baked
into the sandbox image or uploaded as a tarball by `kernel_package.py`. It may only
use the stdlib plus the libraries baked into the notebook sandbox image
(`Dockerfile.sandbox-notebook`): pyarrow, duckdb, pandas, jupyter_client. The image
build imports every module here to hold that rule, so a new third-party import
fails the build rather than the next cold start.

Intra-package imports must stay relative so the code works under both names
(`products.notebooks.backend.kernel` in tests, `nb_kernel` in the sandbox).

See `products/notebooks/backend/sql_v2_kernel_architecture.md` for the design.
"""
