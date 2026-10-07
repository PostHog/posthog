"""The project-wide quotas and caps that stop or delay workflow sends, for the scene-wide notice."""

from products.workflows.backend.services.sending_limits import get_team_sending_limits

__all__ = ["get_team_sending_limits"]
