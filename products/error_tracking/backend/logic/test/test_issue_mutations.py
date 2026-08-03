from django.test import SimpleTestCase

from parameterized import parameterized

from products.error_tracking.backend.logic.issue_mutations import (
    AssigneeValidationError,
    _coerce_role_assignee_id,
    _coerce_user_assignee_id,
)


class TestCoerceAssigneeId(SimpleTestCase):
    def test_user_id_coerced_to_int(self) -> None:
        self.assertEqual(_coerce_user_assignee_id("123"), 123)

    def test_role_id_coerced_to_uuid_string(self) -> None:
        self.assertEqual(
            _coerce_role_assignee_id("019fc6a7-0000-7000-8000-000000000000"),
            "019fc6a7-0000-7000-8000-000000000000",
        )

    @parameterized.expand(
        [
            ("role_uuid_sent_as_user_id", "019fc6a7-0000-7000-8000-000000000000"),
            ("non_numeric", "not-a-number"),
            ("none", None),
        ]
    )
    def test_coerce_user_assignee_id_rejects_non_integer(self, _name: str, raw_id: str | None) -> None:
        with self.assertRaises(AssigneeValidationError):
            _coerce_user_assignee_id(raw_id)

    @parameterized.expand(
        [
            ("malformed_uuid", "not-a-uuid"),
            ("none", None),
        ]
    )
    def test_coerce_role_assignee_id_rejects_non_uuid(self, _name: str, raw_id: str | None) -> None:
        with self.assertRaises(AssigneeValidationError):
            _coerce_role_assignee_id(raw_id)
