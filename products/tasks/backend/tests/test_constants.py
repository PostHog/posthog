import re

from django.conf import settings

from products.tasks.backend.constants import POSTHOG_EXEC_PERMISSION_REGEX
from products.tasks.backend.presentation.serializers import TASK_RUN_ARTIFACT_INLINE_MAX_SIZE_BYTES


def test_exec_permission_regex_only_matches_connected_project_tools():
    pattern = re.compile(POSTHOG_EXEC_PERMISSION_REGEX, re.IGNORECASE)

    assert pattern.search("posthog-connection-call")
    assert pattern.search("posthog-connection-forward")
    assert not pattern.search("feature-flag-delete")


def test_inline_artifact_ceiling_stays_reachable_through_the_request_body_limit():
    # Django raises RequestDataTooBig before the serializer runs, so an inline ceiling that base64
    # inflates past DATA_UPLOAD_MAX_MEMORY_SIZE turns the "use prepare_upload" error into an opaque
    # 400 with no field attached. Raising this ceiling means raising the body limit with it.
    largest_encoded_body = TASK_RUN_ARTIFACT_INLINE_MAX_SIZE_BYTES * 4 // 3

    assert largest_encoded_body < settings.DATA_UPLOAD_MAX_MEMORY_SIZE
