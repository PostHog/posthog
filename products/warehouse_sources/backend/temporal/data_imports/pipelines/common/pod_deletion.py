"""How long Kubernetes still gives this pod once it deletes it.

A drain can kill a pod sooner than its `terminationGracePeriodSeconds`: a Karpenter node pool's
`terminationGracePeriod` caps every pod on the node, and a spot reclaim falls under that cap. Only the
pod's own `deletionTimestamp` shows the real deadline. The read needs a mounted service account token
with `get` on pods in the pod's namespace. Without one, the deadline is unknown.
"""

import os
import socket
import threading
from datetime import UTC, datetime
from pathlib import Path

import requests
import structlog

SERVICE_ACCOUNT_DIR = Path("/var/run/secrets/kubernetes.io/serviceaccount")
# The first caller waits for the read, and that caller can be the event loop.
READ_TIMEOUT_SECONDS = 2.0

logger = structlog.get_logger(__name__)


class PodDeletionDeadline:
    """Reads this pod once, on the first question, and keeps the answer for the process."""

    def __init__(self, service_account_dir: Path = SERVICE_ACCOUNT_DIR, pod_name: str | None = None) -> None:
        self._service_account_dir = service_account_dir
        self._pod_name = pod_name or socket.gethostname()
        self._lock = threading.Lock()
        self._read = False
        self._deadline: datetime | None = None

    def seconds_until_kill(self) -> float | None:
        """Seconds until the kubelet kills this pod, or None while the pod is not being deleted.

        Ask only after the worker got SIGTERM: the timestamp exists only once the deletion started.
        """
        with self._lock:
            if not self._read:
                self._read = True
                self._deadline = self._read_deadline()
        if self._deadline is None:
            return None
        return (self._deadline - datetime.now(UTC)).total_seconds()

    def _read_deadline(self) -> datetime | None:
        token_path = self._service_account_dir / "token"
        host = os.environ.get("KUBERNETES_SERVICE_HOST")
        if host is None or not token_path.exists():
            return None
        if ":" in host:
            host = f"[{host}]"
        port = os.environ.get("KUBERNETES_SERVICE_PORT", "443")
        try:
            namespace = (self._service_account_dir / "namespace").read_text().strip()
            response = requests.get(
                f"https://{host}:{port}/api/v1/namespaces/{namespace}/pods/{self._pod_name}",
                headers={"Authorization": f"Bearer {token_path.read_text().strip()}"},
                verify=str(self._service_account_dir / "ca.crt"),
                timeout=READ_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            deletion = response.json().get("metadata", {}).get("deletionTimestamp")
        except Exception:
            logger.warning("Could not read when Kubernetes kills this pod", exc_info=True)
            return None
        if not deletion:
            return None
        return datetime.fromisoformat(deletion)


POD_DELETION_DEADLINE = PodDeletionDeadline()
