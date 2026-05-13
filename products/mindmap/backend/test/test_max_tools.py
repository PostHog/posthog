from posthog.test.base import BaseTest

from asgiref.sync import sync_to_async
from langchain_core.runnables import RunnableConfig

from products.mindmap.backend.max_tools import (
    ConnectPostItsTool,
    CreatePostItTool,
    DeletePostItTool,
    DisconnectPostItsTool,
    LinkNotebookToPostItTool,
    ListMindMapTool,
    UpdatePostItTool,
)
from products.mindmap.backend.models import MindMapEdge, MindMapPostIt


class TestMindMapMaxTools(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self._config: RunnableConfig = {
            "configurable": {"team": self.team, "user": self.user},
        }

    def _make(self, tool_cls):
        return tool_cls(team=self.team, user=self.user, config=self._config)

    async def test_create_postit(self) -> None:
        tool = self._make(CreatePostItTool)
        message, payload = await tool._arun_impl(title="Onboarding", color="blue", emoji="🚀")
        self.assertIn("short_id", payload)
        self.assertIn("Onboarding", message)
        postit = await sync_to_async(MindMapPostIt.objects.get)(short_id=payload["short_id"])
        self.assertEqual(postit.title, "Onboarding")
        self.assertEqual(postit.color, "blue")
        self.assertEqual(postit.emoji, "🚀")

    async def test_create_postit_with_parents(self) -> None:
        parent = await sync_to_async(MindMapPostIt.objects.create)(team=self.team, title="P")
        tool = self._make(CreatePostItTool)
        _, payload = await tool._arun_impl(title="C", parent_short_ids=[parent.short_id])
        edges = await sync_to_async(list)(MindMapEdge.objects.filter(source=parent).select_related("target"))
        self.assertEqual(len(edges), 1)
        self.assertEqual(edges[0].target.short_id, payload["short_id"])

    async def test_update_postit(self) -> None:
        postit = await sync_to_async(MindMapPostIt.objects.create)(team=self.team, title="A")
        tool = self._make(UpdatePostItTool)
        _, payload = await tool._arun_impl(short_id=postit.short_id, title="B")
        self.assertEqual(payload["title"], "B")

    async def test_delete_postit_drops_edges(self) -> None:
        a = await sync_to_async(MindMapPostIt.objects.create)(team=self.team, title="A")
        b = await sync_to_async(MindMapPostIt.objects.create)(team=self.team, title="B")
        await sync_to_async(MindMapEdge.objects.create)(team=self.team, source=a, target=b)
        tool = self._make(DeletePostItTool)
        await tool._arun_impl(short_id=a.short_id)
        self.assertFalse(await sync_to_async(MindMapEdge.objects.filter(source=a).exists)())

    async def test_connect_idempotent(self) -> None:
        a = await sync_to_async(MindMapPostIt.objects.create)(team=self.team, title="A")
        b = await sync_to_async(MindMapPostIt.objects.create)(team=self.team, title="B")
        tool = self._make(ConnectPostItsTool)
        await tool._arun_impl(source_short_id=a.short_id, target_short_id=b.short_id)
        await tool._arun_impl(source_short_id=a.short_id, target_short_id=b.short_id)
        count = await sync_to_async(MindMapEdge.objects.filter(source=a, target=b).count)()
        self.assertEqual(count, 1)

    async def test_disconnect(self) -> None:
        a = await sync_to_async(MindMapPostIt.objects.create)(team=self.team, title="A")
        b = await sync_to_async(MindMapPostIt.objects.create)(team=self.team, title="B")
        await sync_to_async(MindMapEdge.objects.create)(team=self.team, source=a, target=b)
        tool = self._make(DisconnectPostItsTool)
        await tool._arun_impl(source_short_id=a.short_id, target_short_id=b.short_id)
        self.assertEqual(await sync_to_async(MindMapEdge.objects.count)(), 0)

    async def test_list_mindmap(self) -> None:
        a = await sync_to_async(MindMapPostIt.objects.create)(team=self.team, title="A")
        b = await sync_to_async(MindMapPostIt.objects.create)(team=self.team, title="B")
        await sync_to_async(MindMapEdge.objects.create)(team=self.team, source=a, target=b)
        tool = self._make(ListMindMapTool)
        _, payload = await tool._arun_impl()
        self.assertEqual(len(payload["postits"]), 2)
        self.assertEqual(payload["edges"], [{"source": a.short_id, "target": b.short_id}])

    async def test_link_notebook_unknown_rejected(self) -> None:
        postit = await sync_to_async(MindMapPostIt.objects.create)(team=self.team, title="A")
        tool = self._make(LinkNotebookToPostItTool)
        with self.assertRaises(Exception):
            await tool._arun_impl(postit_short_id=postit.short_id, notebook_short_id="nope")
