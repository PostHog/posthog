import re
import json
from pathlib import Path

GIT_HELPER_PATH = "/run/posthog/git-egress-helper.py"


def git_credential_helper(*, relay_name: str, capability_path: str, repository: str) -> str:
    from products.tasks.backend.logic.services.agent_egress_git import GitReadCredential

    GitReadCredential.validate_repository(repository)
    if not re.fullmatch(r"egress-relay-[0-9a-f]{32}", relay_name):
        raise ValueError("Invalid Git relay name")
    if not Path(capability_path).is_absolute():
        raise ValueError("Invalid Git capability path")
    config = json.dumps(
        {"host": f"{relay_name}:8080", "path": f"v1/git/{repository}.git", "capability": capability_path}
    )
    return f"""import json,sys
from pathlib import Path
config = json.loads({config!r})
if len(sys.argv) != 2 or sys.argv[1] != "get":
    raise SystemExit(0)
fields = dict(line.rstrip("\\n").split("=", 1) for line in sys.stdin if "=" in line)
if fields.get("protocol") != "http" or fields.get("host") != config["host"] or fields.get("path") != config["path"]:
    raise SystemExit(0)
with Path(config["capability"]).open() as source:
    capability = source.read(8193).strip()
if not capability or len(capability) > 8192 or not capability.isascii() or any(c.isspace() or ord(c) < 32 for c in capability):
    raise SystemExit(1)
sys.stdout.write("username=egress\\npassword=" + capability + "\\n")
"""
