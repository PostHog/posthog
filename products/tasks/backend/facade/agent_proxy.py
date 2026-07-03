"""
Facade re-export for the internal agent-proxy callback view.

Core's URLconf routes ``internal/tasks/runs/<run_id>/agent-proxy-callback/`` directly to this
handler, so it must be reachable from outside the product without importing internals directly.
"""

from products.tasks.backend.agent_proxy_callback import agent_proxy_callback

__all__ = ["agent_proxy_callback"]
