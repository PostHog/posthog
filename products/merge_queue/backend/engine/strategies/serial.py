"""Serial strategy: PRs validated on top of the one before, in true merge order, one at a time."""

CONCURRENT = False  # a slot trials only once its single predecessor has cleared
