"""The in-sandbox SQLV2 kernel-server, as a real package.

Nothing here may import Django or posthog — this code is tarred up by
`kernel_package.py`, written into the notebook sandbox, extracted as the
`nb_kernel` package, and launched there (`python -m nb_kernel.server`). It may
only use the stdlib plus the libraries baked into the notebook sandbox image
(`Dockerfile.sandbox-notebook`): pyarrow, duckdb, pandas, jupyter_client.

Intra-package imports must stay relative so the code works under both names
(`products.notebooks.backend.kernel` in tests, `nb_kernel` in the sandbox).

See `products/notebooks/backend/sql_v2_kernel_architecture.md` for the design.
"""
