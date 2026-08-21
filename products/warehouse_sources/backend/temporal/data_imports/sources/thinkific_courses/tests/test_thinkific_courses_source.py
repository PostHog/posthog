from typing import Optional

from unittest.mock import patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.thinkificcourses import (
    ThinkificCoursesSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.thinkific_courses.source import (
    ThinkificCoursesSource,
)

PATCH_VALIDATE = "products.warehouse_sources.backend.temporal.data_imports.sources.thinkific_courses.source.validate_thinkific_credentials"


def _config(api_key: str = "key", subdomain: str = "mycompany") -> ThinkificCoursesSourceConfig:
    return ThinkificCoursesSourceConfig(api_key=api_key, subdomain=subdomain)


class TestThinkificCoursesValidateCredentials:
    def test_rejects_invalid_subdomain_without_calling_api(self) -> None:
        with patch(PATCH_VALIDATE) as mock_validate:
            ok, err = ThinkificCoursesSource().validate_credentials(_config(subdomain="bad domain"), team_id=1)
        assert ok is False
        assert err is not None
        mock_validate.assert_not_called()

    def test_valid_credentials(self) -> None:
        with patch(PATCH_VALIDATE, return_value=(True, 200)):
            ok, err = ThinkificCoursesSource().validate_credentials(_config(), team_id=1)
        assert ok is True
        assert err is None

    @parameterized.expand(
        [
            # (status, schema_name, expected_ok) - 403 at source-create (schema None) is accepted, but a
            # per-schema 403 is surfaced as a failure.
            ("forbidden_at_create", 403, None, True),
            ("forbidden_for_schema", 403, "courses", False),
            ("unauthorized_at_create", 401, None, False),
        ]
    )
    def test_status_handling(self, _name: str, status: int, schema_name: Optional[str], expected_ok: bool) -> None:
        with patch(PATCH_VALIDATE, return_value=(False, status)):
            ok, _err = ThinkificCoursesSource().validate_credentials(_config(), team_id=1, schema_name=schema_name)
        assert ok is expected_ok

    @parameterized.expand(
        [
            # Fan-out schemas can't be probed directly (their path needs a parent id), so the check
            # must probe the parent list endpoint instead of the templated child path.
            ("fanout_probes_parent", "course_reviews", "/courses"),
            ("fanout_probes_promotions_parent", "coupons", "/promotions"),
            ("top_level_probes_itself", "enrollments", "/enrollments"),
        ]
    )
    def test_schema_probe_path(self, _name: str, schema_name: str, expected_path: str) -> None:
        with patch(PATCH_VALIDATE, return_value=(True, 200)) as mock_validate:
            ThinkificCoursesSource().validate_credentials(_config(), team_id=1, schema_name=schema_name)
        assert mock_validate.call_args.args[2] == expected_path
