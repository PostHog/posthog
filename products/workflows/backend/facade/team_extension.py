"""Facade re-export for the workflows team-extension model.

Core's ``Team.workflows_config`` accessor and ``posthog/api/team.py`` register/read this
extension by class identity through ``get_or_create_team_extension``. Re-exporting the model
class keeps that registry coupling at the facade boundary without exposing the internal models
package.
"""

from products.workflows.backend.models.team_workflows_config import TeamWorkflowsConfig

__all__ = ["TeamWorkflowsConfig"]
