from posthog.test.base import BaseTest

from django.core.exceptions import ValidationError

from products.mindmap.backend import service
from products.mindmap.backend.models import MindMapEdge, MindMapPostIt
from products.notebooks.backend.models import Notebook


class TestService(BaseTest):
    def test_create_postit_minimal(self) -> None:
        postit = service.create_postit(team=self.team, user=self.user, title="Hello")
        self.assertEqual(postit.title, "Hello")
        self.assertEqual(postit.team_id, self.team.pk)
        self.assertEqual(postit.created_by_id, self.user.pk)
        self.assertEqual(postit.color, MindMapPostIt.Color.YELLOW)

    def test_create_postit_with_parents_creates_edges(self) -> None:
        parent = service.create_postit(team=self.team, user=self.user, title="P")
        child = service.create_postit(team=self.team, user=self.user, title="C", parent_short_ids=[parent.short_id])
        edge = MindMapEdge.objects.get(source=parent, target=child)
        self.assertEqual(edge.team_id, self.team.pk)

    def test_create_postit_assigns_grid_position(self) -> None:
        first = service.create_postit(team=self.team, user=self.user, title="A")
        second = service.create_postit(team=self.team, user=self.user, title="B")
        self.assertNotEqual((first.position_x, first.position_y), (second.position_x, second.position_y))

    def test_update_postit_partial(self) -> None:
        postit = service.create_postit(team=self.team, user=self.user, title="T")
        updated = service.update_postit(team=self.team, user=self.user, short_id=postit.short_id, body="new")
        self.assertEqual(updated.body, "new")
        self.assertEqual(updated.title, "T")

    def test_update_postit_clear_notebook(self) -> None:
        notebook = Notebook.objects.create(team=self.team, title="nb")
        postit = service.create_postit(team=self.team, user=self.user, title="T", notebook_short_id=notebook.short_id)
        cleared = service.update_postit(
            team=self.team,
            user=self.user,
            short_id=postit.short_id,
            notebook_short_id=None,
        )
        self.assertIsNone(cleared.notebook_short_id)

    def test_delete_postit_soft_deletes_and_drops_edges(self) -> None:
        a = service.create_postit(team=self.team, user=self.user, title="A")
        b = service.create_postit(team=self.team, user=self.user, title="B")
        service.connect(team=self.team, user=self.user, source_short_id=a.short_id, target_short_id=b.short_id)
        service.delete_postit(team=self.team, user=self.user, short_id=a.short_id)
        a.refresh_from_db()
        self.assertTrue(a.deleted)
        self.assertFalse(MindMapEdge.objects.filter(source=a).exists())
        self.assertFalse(MindMapEdge.objects.filter(target=a).exists())

    def test_connect_idempotent(self) -> None:
        a = service.create_postit(team=self.team, user=self.user, title="A")
        b = service.create_postit(team=self.team, user=self.user, title="B")
        e1 = service.connect(team=self.team, user=self.user, source_short_id=a.short_id, target_short_id=b.short_id)
        e2 = service.connect(team=self.team, user=self.user, source_short_id=a.short_id, target_short_id=b.short_id)
        self.assertEqual(e1.pk, e2.pk)
        self.assertEqual(MindMapEdge.objects.filter(source=a, target=b).count(), 1)

    def test_connect_rejects_self_loop(self) -> None:
        a = service.create_postit(team=self.team, user=self.user, title="A")
        with self.assertRaises(ValidationError):
            service.connect(team=self.team, user=self.user, source_short_id=a.short_id, target_short_id=a.short_id)

    def test_disconnect_no_op_when_missing(self) -> None:
        a = service.create_postit(team=self.team, user=self.user, title="A")
        b = service.create_postit(team=self.team, user=self.user, title="B")
        service.disconnect(team=self.team, user=self.user, source_short_id=a.short_id, target_short_id=b.short_id)
        self.assertEqual(MindMapEdge.objects.count(), 0)

    def test_notebook_validation_rejects_unknown_short_id(self) -> None:
        with self.assertRaises(ValidationError):
            service.create_postit(team=self.team, user=self.user, title="T", notebook_short_id="doesnotexist")

    def test_bulk_position_updates_known_postits(self) -> None:
        a = service.create_postit(team=self.team, user=self.user, title="A")
        b = service.create_postit(team=self.team, user=self.user, title="B")
        updated = service.bulk_position(
            team=self.team,
            user=self.user,
            updates=[
                {"short_id": a.short_id, "position_x": 50.0, "position_y": 75.0},
                {"short_id": b.short_id, "position_x": -10.0, "position_y": 0.0},
                {"short_id": "unknown", "position_x": 0.0, "position_y": 0.0},
            ],
        )
        a.refresh_from_db()
        b.refresh_from_db()
        self.assertEqual(updated, 2)
        self.assertEqual((a.position_x, a.position_y), (50.0, 75.0))
        self.assertEqual((b.position_x, b.position_y), (-10.0, 0.0))
