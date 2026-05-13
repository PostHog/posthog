from posthog.test.base import BaseTest

from django.db import IntegrityError
from django.db.transaction import atomic

from products.mindmap.backend.models import MindMapEdge, MindMapPostIt


class TestMindMapPostIt(BaseTest):
    def test_create_with_defaults(self) -> None:
        postit = MindMapPostIt.objects.create(team=self.team, title="Hello")
        self.assertEqual(postit.color, MindMapPostIt.Color.YELLOW)
        self.assertEqual(postit.body, "")
        self.assertEqual(postit.emoji, "")
        self.assertFalse(postit.deleted)
        self.assertEqual(postit.position_x, 0.0)
        self.assertEqual(postit.position_y, 0.0)
        self.assertTrue(postit.short_id)

    def test_short_id_unique_per_team(self) -> None:
        a = MindMapPostIt.objects.create(team=self.team, title="A")
        with atomic(), self.assertRaises(IntegrityError):
            MindMapPostIt.objects.create(team=self.team, title="B", short_id=a.short_id)


class TestMindMapEdge(BaseTest):
    def _postit(self, title: str = "n") -> MindMapPostIt:
        return MindMapPostIt.objects.create(team=self.team, title=title)

    def test_create_edge(self) -> None:
        a, b = self._postit("a"), self._postit("b")
        edge = MindMapEdge.objects.create(team=self.team, source=a, target=b)
        self.assertEqual(edge.source_id, a.id)
        self.assertEqual(edge.target_id, b.id)

    def test_self_loop_rejected(self) -> None:
        a = self._postit("a")
        with atomic(), self.assertRaises(IntegrityError):
            MindMapEdge.objects.create(team=self.team, source=a, target=a)

    def test_duplicate_edge_rejected(self) -> None:
        a, b = self._postit("a"), self._postit("b")
        MindMapEdge.objects.create(team=self.team, source=a, target=b)
        with atomic(), self.assertRaises(IntegrityError):
            MindMapEdge.objects.create(team=self.team, source=a, target=b)
