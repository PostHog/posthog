from django.test import SimpleTestCase

from parameterized import parameterized

from products.tasks.backend.client_analytics import run_client_properties


class TestRunClientProperties(SimpleTestCase):
    @parameterized.expand(
        [
            ("mobile_to_web", {"client_surface": "web", "$session_id": "web-session"}, "web"),
            ("mobile_to_mobile", {"client_surface": "mobile", "client_action_id": "message-a"}, "mobile"),
            ("unknown_resume", {}, None),
        ]
    )
    def test_run_origin_uses_the_current_initiation_not_an_inherited_mobile_marker(
        self, _name: str, context: dict[str, str], expected_surface: str | None
    ) -> None:
        properties = run_client_properties(
            {"creation_client_context": {"client_surface": "mobile"}},
            {"client_platform": "mobile", "run_client_context": context},
        )
        assert properties["task_created_surface"] == "mobile"
        assert properties["run_started_surface"] == expected_surface
        assert properties["initiating_surface"] == expected_surface
        assert properties["initiating_session_id"] == context.get("$session_id")
        assert properties["initiating_action_id"] == context.get("client_action_id")
