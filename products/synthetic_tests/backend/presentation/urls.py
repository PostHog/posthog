"""URL routes for synthetic_tests."""

from .views import SyntheticTestRunViewSet, SyntheticTestViewSet

# Registered under the project-scoped router in posthog/api/__init__.py
# Exposes:
#   /api/projects/:team_id/synthetic_tests/                (list, create)
#   /api/projects/:team_id/synthetic_tests/:id/            (retrieve, update, destroy)
#   /api/projects/:team_id/synthetic_tests/:id/run_now/    (POST)
#   /api/projects/:team_id/synthetic_tests/:id/pause/      (POST)
#   /api/projects/:team_id/synthetic_tests/:id/resume/     (POST)
#   /api/projects/:team_id/synthetic_tests/generate_from_replay/  (POST)
#   /api/projects/:team_id/synthetic_test_runs/            (list, retrieve)

__all__ = ["SyntheticTestViewSet", "SyntheticTestRunViewSet"]
