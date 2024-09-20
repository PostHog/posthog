# Common crates for the hog-rs services

This folder holds internal crates for code reuse between services in the monorepo. To keep maintenance costs low,
these crates should ideally:

- Cover a small feature scope and use as little dependencies as possible
- Only use `{ workspace = true }` dependencies, instead of pinning versions that could diverge from the workspace
- Have adequate test coverage and documentation
