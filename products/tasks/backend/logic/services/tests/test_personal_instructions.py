from typing import ClassVar

from django.test import TestCase

from parameterized import parameterized

from posthog.models.organization import Organization
from posthog.models.team.team import Team
from posthog.models.user import User

from products.tasks.backend.facade import api as facade
from products.tasks.backend.logic.services.personal_instructions import (
    PERSONAL_INSTRUCTIONS_APPLIED_STATE_KEY,
    build_first_message,
    format_personal_instructions,
)
from products.tasks.backend.models import CODE_CUSTOM_INSTRUCTIONS_MAX_LENGTH, Task, TaskRun

_OPEN_TAG = "<user_custom_instructions>"
_CLOSE_TAG = "</user_custom_instructions>"


class TestFormatPersonalInstructions(TestCase):
    def test_defangs_nested_closing_tag(self):
        formatted = format_personal_instructions(f"before {_CLOSE_TAG} after")
        assert formatted.count(_CLOSE_TAG) == 1
        assert formatted.endswith(_CLOSE_TAG)
        assert "<\\/user_custom_instructions>" in formatted

    def test_truncates_to_cap(self):
        formatted = format_personal_instructions("x" * (CODE_CUSTOM_INSTRUCTIONS_MAX_LENGTH + 500))
        assert "x" * CODE_CUSTOM_INSTRUCTIONS_MAX_LENGTH in formatted
        assert "x" * (CODE_CUSTOM_INSTRUCTIONS_MAX_LENGTH + 1) not in formatted

    def test_blank_content_returns_empty(self):
        assert format_personal_instructions("   \n  ") == ""


class TestBuildFirstMessage(TestCase):
    org: ClassVar[Organization]
    team: ClassVar[Team]
    user: ClassVar[User]

    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name="Org")
        cls.team = Team.objects.create(organization=cls.org, name="Team")
        cls.user = User.objects.create(email="actor@test.com", distinct_id="actor")

    def _task(self, origin=Task.OriginProduct.USER_CREATED) -> Task:
        return Task.objects.create(
            team=self.team,
            title="t",
            description="d",
            origin_product=origin,
            created_by=self.user,
        )

    def _run(self, task: Task, state: dict | None = None) -> TaskRun:
        return TaskRun.objects.create(task=task, team=self.team, status=TaskRun.Status.IN_PROGRESS, state=state or {})

    def _set_instructions(self, content: str) -> None:
        seed = facade.get_code_custom_instructions(self.team.id, self.user.id)
        facade.save_code_custom_instructions(self.team.id, self.user.id, content=content, expected_version=seed.version)

    def test_allowed_origin_with_content_prepends_and_marks(self):
        self._set_instructions("Prefer tabs over spaces.")
        run = self._run(self._task())

        message, should_mark = build_first_message(run, "fix the bug", self.user)

        assert should_mark is True
        assert message is not None
        assert message.endswith("fix the bug")
        assert _OPEN_TAG in message
        assert "Prefer tabs over spaces." in message

    @parameterized.expand(
        [
            (Task.OriginProduct.SIGNAL_REPORT,),
            (Task.OriginProduct.SIGNALS_SCOUT,),
            (Task.OriginProduct.SUPPORT_REPLY,),
            (Task.OriginProduct.ONBOARDING,),
            (Task.OriginProduct.AUTOMATION,),
        ]
    )
    def test_autonomous_origins_never_injected(self, origin):
        self._set_instructions("Prefer tabs.")
        run = self._run(self._task(origin))

        message, should_mark = build_first_message(run, "do the thing", self.user)

        assert message == "do the thing"
        assert should_mark is False

    def test_no_actor_user_skips(self):
        self._set_instructions("Prefer tabs.")
        run = self._run(self._task())

        message, should_mark = build_first_message(run, "hello", None)

        assert message == "hello"
        assert should_mark is False

    def test_already_applied_flag_skips(self):
        self._set_instructions("Prefer tabs.")
        run = self._run(self._task(), state={PERSONAL_INSTRUCTIONS_APPLIED_STATE_KEY: True})

        message, should_mark = build_first_message(run, "hello", self.user)

        assert message == "hello"
        assert should_mark is False

    def test_message_with_existing_block_is_deduped_but_marked(self):
        self._set_instructions("Prefer tabs.")
        run = self._run(self._task())
        folded = f"{_OPEN_TAG}\nclient-folded\n{_CLOSE_TAG}\n\nfix it"

        message, should_mark = build_first_message(run, folded, self.user)

        assert message == folded
        assert should_mark is True

    def test_empty_stored_content_marks_without_injecting(self):
        self._set_instructions("")
        run = self._run(self._task())

        message, should_mark = build_first_message(run, "hello", self.user)

        assert message == "hello"
        assert should_mark is True

    def test_empty_message_is_untouched(self):
        self._set_instructions("Prefer tabs.")
        run = self._run(self._task())

        message, should_mark = build_first_message(run, None, self.user)

        assert message is None
        assert should_mark is False
