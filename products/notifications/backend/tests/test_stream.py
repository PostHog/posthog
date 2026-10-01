from django.test import SimpleTestCase

import orjson
from parameterized import parameterized

from products.notifications.backend.presentation.stream import filter_notification_for_user


class TestFilterNotificationForUser(SimpleTestCase):
    @parameterized.expand(
        [
            (
                "recipient",
                b'{"id": "n1", "title": "Hi", "resolved_user_ids": [7, 42]}',
                42,
                {"id": "n1", "title": "Hi"},
            ),
            ("wrong_user", b'{"id": "n1", "resolved_user_ids": [7, 8]}', 42, None),
            ("missing_key", b'{"id": "n1"}', 42, None),
            ("non_list_key", b'{"id": "n1", "resolved_user_ids": 42}', 42, None),
            ("string_ids", b'{"id": "n1", "resolved_user_ids": ["42"]}', 42, None),
            ("boolean_id", b'{"id": "n1", "resolved_user_ids": [true]}', 1, None),
            ("malformed_json", b'{"id": "n1", "resolved_user_ids": [42', 42, None),
            ("non_object_json", b"[42]", 42, None),
        ]
    )
    def test_filter(self, _name: str, payload: bytes, user_id: int, expected: dict | None) -> None:
        result = filter_notification_for_user(payload, user_id)

        if expected is None:
            assert result is None
        else:
            assert result is not None
            assert orjson.loads(result) == expected
