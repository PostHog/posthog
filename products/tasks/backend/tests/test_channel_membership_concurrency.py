from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from queue import Queue
from time import monotonic
from uuid import UUID

from posthog.test.base import NonAtomicBaseTest

from django.db import close_old_connections, connection, transaction

from posthog.models import Team, User
from posthog.models.scoping import team_scope

from products.tasks.backend.facade import api as facade
from products.tasks.backend.models import (
    Channel,
    ChannelContextGeneration,
    ChannelFeedMessage,
    ChannelInstructions,
    ChannelMembership,
    ChannelStar,
    Task,
    TaskThreadMessage,
)


class TestChannelMembershipConcurrency(NonAtomicBaseTest):
    CLASS_DATA_LEVEL_SETUP = False

    def test_pending_writes_recheck_membership_after_revocation(self) -> None:
        team = self.team
        owner = self.user
        member = User.objects.create(email="member@example.com")
        self.organization.members.add(member)
        for operation, expected in [
            ("update", "not_found"),
            ("delete", "not_found"),
            ("members", "not_found"),
            ("feed", None),
            ("publish_instructions", None),
            ("delete_instructions", None),
            ("context_generation", "not_found"),
            ("star", False),
            ("handoff", None),
            ("handoff_after_move", None),
        ]:
            with self.subTest(operation=operation):
                self._assert_pending_write_rejected(team, owner, member, operation, expected)

    def _assert_pending_write_rejected(
        self, team: Team, owner: User, member: User, operation: str, expected: str | bool | None
    ) -> None:
        with team_scope(team.id):
            channel = facade.create_private_channel(team.id, owner.id, name="squad", member_ids=[member.id], star=False)
            assert channel is not None
            facade.publish_channel_instructions(channel.id, team.id, owner.id, content="Original instructions")

        mutations: dict[str, Callable[[str | UUID, int, int], object]] = {
            "update": partial(facade.update_channel, name="renamed", can_manage_shared_auto_archive=True),
            "delete": facade.delete_channel,
            "members": partial(facade.set_channel_members, member_ids=[member.id]),
            "feed": partial(facade.create_channel_feed_message, event="task_created", payload={}),
            "publish_instructions": partial(facade.publish_channel_instructions, content="Overwritten"),
            "delete_instructions": facade.delete_channel_instructions,
            "context_generation": partial(facade.set_channel_context_generation, task_id=None),
            "star": partial(facade.star_channel, starred=True),
        }
        task = None
        recipient = None
        resource_id = channel.id
        if operation in ("handoff", "handoff_after_move"):
            recipient = User.objects.create(email=f"recipient-{operation}@example.com")
            self.organization.members.add(recipient)
            task = Task.objects.create(
                team=team,
                channel_id=channel.id,
                created_by=member,
                title="Transfer task",
                origin_product=Task.OriginProduct.USER_CREATED,
            )
            resource_id = task.id
            mutations[operation] = partial(facade.handoff_task, target_user_id=recipient.id)

        def revoke() -> None:
            if operation == "handoff_after_move":
                assert task is not None
                Task.objects.filter(id=task.id, team_id=team.id).update(channel=None)
                return
            result = facade.set_channel_members(channel.id, team.id, owner.id, member_ids=[])
            self.assertIsInstance(result, list)

        result = self._run_pending_write(
            channel.id, team.id, partial(mutations[operation], resource_id, team.id, member.id), revoke
        )
        self.assertEqual(result, expected)
        if task is not None and recipient is not None:
            task.refresh_from_db()
            self.assertEqual(task.created_by_id, member.id)
            self.assertEqual(task.channel_id, None if operation == "handoff_after_move" else channel.id)
            self.assertFalse(
                ChannelMembership.objects.for_team(team.id).filter(channel_id=channel.id, user_id=recipient.id).exists()
            )
            self.assertFalse(TaskThreadMessage.objects.for_team(team.id).filter(task_id=task.id).exists())

        with team_scope(team.id):
            persisted = Channel.objects.get(id=channel.id)
            self.assertEqual(persisted.name, "squad")
            self.assertFalse(persisted.deleted)
            self.assertEqual(ChannelFeedMessage.objects.filter(channel_id=channel.id).count(), 1)
            self.assertFalse(ChannelContextGeneration.objects.filter(channel_id=channel.id).exists())
            self.assertFalse(ChannelStar.objects.filter(channel_id=channel.id).exists())
            instructions = ChannelInstructions.objects.get(channel_id=channel.id)
            self.assertEqual(instructions.content, "Original instructions")
            self.assertFalse(instructions.deleted)

    def test_pending_membership_replacement_revalidates_project_access(self) -> None:
        candidate = User.objects.create(email="candidate@example.com")
        self.organization.members.add(candidate)
        with team_scope(self.team.id):
            channel = facade.create_private_channel(self.team.id, self.user.id, name="squad", member_ids=[], star=False)
        assert channel is not None
        result = self._run_pending_write(
            channel.id,
            self.team.id,
            partial(facade.set_channel_members, channel.id, self.team.id, self.user.id, member_ids=[candidate.id]),
            partial(self.organization.members.remove, candidate),
        )
        self.assertEqual(result, "invalid_member")
        self.assertFalse(
            ChannelMembership.objects.for_team(self.team.id)
            .filter(channel_id=channel.id, user_id=candidate.id)
            .exists()
        )

    def _run_pending_write(
        self, channel_id: UUID, team_id: int, mutation: Callable[[], object], change: Callable[[], None]
    ) -> object:
        backend_pid: Queue[int] = Queue()

        def write() -> object:
            close_old_connections()
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SET statement_timeout = '10s'")
                    cursor.execute("SELECT pg_backend_pid()")
                    backend_pid.put(cursor.fetchone()[0])
                with team_scope(team_id):
                    return mutation()
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=1) as executor:
            with transaction.atomic(), team_scope(team_id):
                Channel.objects.for_team(team_id).select_for_update().get(id=channel_id)
                pending = executor.submit(write)
                pid = backend_pid.get(timeout=10)
                deadline = monotonic() + 10
                with connection.cursor() as cursor:
                    while not pending.done():
                        cursor.execute("SELECT cardinality(pg_blocking_pids(%s)) > 0", [pid])
                        if cursor.fetchone()[0]:
                            break
                        self.assertLess(monotonic(), deadline, "write did not reach the locked channel")
                change()
            return pending.result(timeout=10)
