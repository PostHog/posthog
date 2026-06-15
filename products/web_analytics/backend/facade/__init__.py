"""Public interface of the web_analytics product.

External code (core, other products) may import from this package only:
`api` for data capabilities, and the capability submodules (`queries`,
`hogql`, `temporal`, `dags`) for wiring that core registers or dispatches on.
"""
