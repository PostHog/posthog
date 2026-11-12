from datetime import UTC, datetime

from posthog.test.base import BaseTest

from django.contrib.messages import get_messages

from parameterized import parameterized

from posthog.personhog_client.fake_client import get_active_fake
from posthog.test.persons import create_group_type_mapping, update_group_type_mapping


class TestGroupTypesConsolePanel(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.user.is_staff = True
        self.user.save()
        self.client.force_login(self.user)

    @parameterized.expand(
        [
            (
                "rename_keeps_the_created_time",
                {"name_singular": "Company"},
                ["name_singular"],
                None,
                "Singular name: Not set to Company",
            ),
            (
                "created_time_to_the_millisecond",
                {"created_at": "2026-02-20 08:15:00.456"},
                ["created_at"],
                int(datetime(2026, 2, 20, 8, 15, tzinfo=UTC).timestamp() * 1000) + 456,
                "Created (UTC): 2026-01-15 10:30:00.123 to 2026-02-20 08:15:00.456",
            ),
            (
                "cleared_created_time",
                {"created_at": ""},
                ["created_at"],
                None,
                "Created (UTC): 2026-01-15 10:30:00.123 to Not set",
            ),
            (
                "cleared_default_columns",
                {"default_columns": ""},
                ["default_columns"],
                None,
                'Default columns: ["name"] to Not set',
            ),
            ("unchanged_form", {}, None, None, ""),
            ("invalid_created_time", {"created_at": "not-a-datetime"}, None, None, ""),
            ("impossible_created_time", {"created_at": "2026-02-30 10:30:00"}, None, None, ""),
        ]
    )
    def test_editing_a_group_type_previews_then_writes_only_the_changed_fields(
        self,
        _name: str,
        changes: dict[str, str],
        expected_mask: list[str] | None,
        expected_created_at: int | None,
        expected_message: str,
    ) -> None:
        create_group_type_mapping(
            team=self.team,
            project_id=self.team.project_id,
            group_type="organization",
            group_type_index=0,
            default_columns=["name"],
            created_at=datetime(2026, 1, 15, 10, 30, 0, 123000, tzinfo=UTC),
        )
        url = f"/admin/console/teams/{self.team.pk}/group-types/edit-0/"
        prefilled = self.client.get(url).context["form"].initial

        preview = self.client.post(url, {**prefilled, **changes, "reason": "Customer asked"})
        updates = [call.request for call in get_active_fake().calls if call.method == "update_group_type_mapping"]
        assert updates == []
        if expected_mask is None:
            assert preview.status_code == 400
            return
        assert preview.status_code == 200
        assert "After saving" in preview.content.decode()

        saved = self.client.post(url, {"confirm_token": preview.context["confirm_token"]})

        assert saved.status_code == 302
        updates = [call.request for call in get_active_fake().calls if call.method == "update_group_type_mapping"]
        assert len(updates) == 1
        assert list(updates[0].update_mask) == expected_mask
        if "created_at" in expected_mask:
            assert (updates[0].created_at if updates[0].HasField("created_at") else None) == expected_created_at
        assert expected_message in " ".join(str(message) for message in get_messages(saved.wsgi_request))

    @parameterized.expand([("before_the_preview", True), ("before_the_confirm", False)])
    def test_editing_a_group_type_refuses_when_the_group_type_changed_since_the_form_opened(
        self, _name: str, change_before_preview: bool
    ) -> None:
        mapping = create_group_type_mapping(
            team=self.team,
            project_id=self.team.project_id,
            group_type="organization",
            group_type_index=0,
            default_columns=["name"],
        )
        url = f"/admin/console/teams/{self.team.pk}/group-types/edit-0/"
        prefilled = self.client.get(url).context["form"].initial
        mapping.default_columns = ["name", "email"]

        if change_before_preview:
            update_group_type_mapping(mapping)
        preview = self.client.post(url, {**prefilled, "name_singular": "Company", "reason": "Customer asked"})
        if change_before_preview:
            assert preview.status_code == 400
            assert "changed since you opened this form" in preview.content.decode()
            return
        update_group_type_mapping(mapping)
        saved = self.client.post(url, {"confirm_token": preview.context["confirm_token"]})

        assert saved.status_code == 409
        assert "changed since you opened this form" in saved.content.decode()
        updates = [call.request for call in get_active_fake().calls if call.method == "update_group_type_mapping"]
        assert updates == []
