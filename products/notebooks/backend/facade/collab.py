"""
Facade re-exports for collaborative-edit publishing.

Callers that persist notebook edits outside the notebooks views (e.g. agent
tooling) publish the resulting update to the collab stream through these
re-exports rather than importing ``backend.markdown_collab`` directly.
"""

from ..markdown_collab import (
    MarkdownDiff as MarkdownDiff,
    apublish_notebook_update as apublish_notebook_update,
    build_markdown_update_diff as build_markdown_update_diff,
    publish_notebook_update as publish_notebook_update,
)
