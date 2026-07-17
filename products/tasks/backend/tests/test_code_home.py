from django.test import TestCase
from django.utils import timezone as django_timezone

from parameterized import parameterized

from posthog.models import Organization, Team, User

from products.tasks.backend.facade import api as tasks_facade
from products.tasks.backend.models import CodeWorkstream, Task


class GetCodeHomeFilteringTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.organization = Organization.objects.create(name="Test Org")
        cls.team = Team.objects.create(organization=cls.organization, name="Test Team")
        cls.user = User.objects.create_user(email="home@example.com", first_name="Home", password="password")
        cls.organization.members.add(cls.user)

    def _create_task(self, *, archived: bool = False, deleted: bool = False) -> Task:
        return Task.objects.create(
            team=self.team,
            created_by=self.user,
            title="Test Task",
            description="Test Description",
            origin_product=Task.OriginProduct.USER_CREATED,
            archived=archived,
            deleted=deleted,
        )

    def _create_workstream(self, *tasks: Task, key: str = "branch:o/r#feature") -> CodeWorkstream:
        return CodeWorkstream.objects.create(
            team=self.team,
            user=self.user,
            key=key,
            state=CodeWorkstream.WorkstreamState.IN_PROGRESS,
            tasks=[{"id": str(t.id), "title": t.title, "status": "completed"} for t in tasks],
            last_activity_at=django_timezone.now(),
        )

    def test_live_task_workstream_is_returned(self):
        task = self._create_task()
        self._create_workstream(task)

        home = tasks_facade.get_code_home(self.team.id, self.user.id)

        self.assertEqual(len(home.in_progress), 1)
        self.assertEqual([t.id for t in home.in_progress[0].tasks], [str(task.id)])

    @parameterized.expand([("archived", {"archived": True}), ("deleted", {"deleted": True})])
    def test_workstream_with_only_unactionable_task_is_hidden(self, _name, task_kwargs):
        task = self._create_task(**task_kwargs)
        self._create_workstream(task)

        home = tasks_facade.get_code_home(self.team.id, self.user.id)

        self.assertEqual(home.in_progress, [])
        self.assertEqual(home.needs_attention, [])

    def test_only_unactionable_tasks_are_dropped_from_a_mixed_workstream(self):
        live = self._create_task()
        archived = self._create_task(archived=True)
        self._create_workstream(live, archived)

        home = tasks_facade.get_code_home(self.team.id, self.user.id)

        self.assertEqual(len(home.in_progress), 1)
        self.assertEqual([t.id for t in home.in_progress[0].tasks], [str(live.id)])
