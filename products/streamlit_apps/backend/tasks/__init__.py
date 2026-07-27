# Re-export tasks for Celery autodiscover
from products.streamlit_apps.backend.tasks.tasks import (
    auto_restart_crashed_streamlit_sandboxes,
    cleanup_deleted_streamlit_app_zips,
    cleanup_expired_streamlit_oauth_tokens,
    prune_old_streamlit_app_versions,
    reset_streamlit_app_restart_count_if_stable,
    run_streamlit_app_lifecycle,
    stop_idle_streamlit_sandboxes,
)

__all__ = [
    "auto_restart_crashed_streamlit_sandboxes",
    "cleanup_deleted_streamlit_app_zips",
    "cleanup_expired_streamlit_oauth_tokens",
    "prune_old_streamlit_app_versions",
    "reset_streamlit_app_restart_count_if_stable",
    "run_streamlit_app_lifecycle",
    "stop_idle_streamlit_sandboxes",
]
