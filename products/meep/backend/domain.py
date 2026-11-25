import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

from django.core.serializers.json import DjangoJSONEncoder
from django.utils import timezone

from rest_framework.exceptions import ValidationError


# The desktop and API run the same pure state transitions. Only Django performs IO.
def transition(operation: str, state: dict | None, envelope: dict) -> dict[str, Any]:
    binary = shutil.which("meep-domain") or Path(__file__).resolve().parents[1] / "domain/target/debug/meep-domain"
    payload = {"operation": operation, "state": state, "envelope": envelope, "now": timezone.now()}
    result = subprocess.run(
        [binary],
        input=json.dumps(payload, cls=DjangoJSONEncoder),
        capture_output=True,
        text=True,
        timeout=10,
        check=True,
    )
    response = json.loads(result.stdout)
    if "error" in response:
        raise ValidationError(response["error"])
    return response["state"]
