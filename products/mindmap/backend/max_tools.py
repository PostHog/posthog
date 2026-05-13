from textwrap import dedent
from typing import Any, Literal

from asgiref.sync import sync_to_async
from pydantic import BaseModel, Field

from products.mindmap.backend import service
from products.mindmap.backend.models import MindMapPostIt

from ee.hogai.tool import MaxTool

COLOR_LITERAL = Literal["yellow", "pink", "blue", "green", "purple", "orange", "gray"]


def _postit_dict(p: MindMapPostIt) -> dict[str, Any]:
    return {
        "short_id": p.short_id,
        "title": p.title,
        "body": p.body,
        "color": p.color,
        "emoji": p.emoji,
        "position_x": p.position_x,
        "position_y": p.position_y,
        "notebook_short_id": p.notebook_short_id,
    }


# ---- list_mindmap ----


class ListMindMapArgs(BaseModel):
    pass


class ListMindMapTool(MaxTool):
    name: str = "list_mindmap"
    description: str = dedent(
        """
        Return the full team mindmap: every post-it and every edge.

        Use this BEFORE making edits if you don't already know what's on the canvas.
        Returns {postits: [...], edges: [{source, target}, ...]}.
        """
    ).strip()
    args_schema: type[BaseModel] = ListMindMapArgs

    async def _arun_impl(self, _args: dict[str, Any]) -> dict[str, Any]:
        # service.list_mindmap uses select_related so source/target are pre-fetched.
        state = await sync_to_async(service.list_mindmap)(team=self._team)
        return {
            "postits": [_postit_dict(p) for p in state.postits],
            "edges": [{"source": e.source.short_id, "target": e.target.short_id} for e in state.edges],
        }


# ---- create_postit ----


class CreatePostItArgs(BaseModel):
    title: str = Field(description="Short title displayed on the post-it (1-256 chars)")
    body: str | None = Field(default=None, description="Optional longer body text")
    color: COLOR_LITERAL | None = Field(default=None, description="Background color tag")
    emoji: str | None = Field(default=None, description="Optional single emoji")
    position_x: float | None = Field(default=None, description="Canvas X (omit to auto-place)")
    position_y: float | None = Field(default=None, description="Canvas Y (omit to auto-place)")
    notebook_short_id: str | None = Field(default=None, description="Notebook short_id to link to")
    parent_short_ids: list[str] | None = Field(
        default=None, description="Existing post-its that should point INTO this new one"
    )
    child_short_ids: list[str] | None = Field(
        default=None, description="Existing post-its this new one should point AT"
    )


class CreatePostItTool(MaxTool):
    name: str = "create_postit"
    description: str = dedent(
        """
        Create a new post-it on the team mindmap.

        - `title` is required and short (1-256 chars). Put long-form content in the linked notebook, not in `body`.
        - Omit `position_x`/`position_y` to let the canvas auto-place the post-it on the next free grid slot.
        - Use `parent_short_ids` and `child_short_ids` to wire arrows in the same step.
        - Returns {short_id, ...full post-it...}.
        """
    ).strip()
    args_schema: type[BaseModel] = CreatePostItArgs

    async def _arun_impl(self, args: dict[str, Any]) -> dict[str, Any]:
        kwargs = {k: v for k, v in args.items() if v is not None}

        def _do_create() -> dict[str, Any]:
            postit = service.create_postit(team=self._team, user=self._user, **kwargs)
            return _postit_dict(postit)

        return await sync_to_async(_do_create)()


# ---- update_postit ----


class UpdatePostItArgs(BaseModel):
    short_id: str = Field(description="The post-it to update")
    title: str | None = Field(default=None, description="New title (omit to leave unchanged)")
    body: str | None = Field(default=None, description="New body text (omit to leave unchanged)")
    color: COLOR_LITERAL | None = Field(default=None, description="New color (omit to leave unchanged)")
    emoji: str | None = Field(default=None, description="New emoji (omit to leave unchanged)")
    position_x: float | None = Field(default=None, description="New X (omit to leave unchanged)")
    position_y: float | None = Field(default=None, description="New Y (omit to leave unchanged)")
    notebook_short_id: str | None = Field(
        default=None,
        description="Set to a notebook short_id to link, set to null/empty string to unlink, omit to leave unchanged",
    )


class UpdatePostItTool(MaxTool):
    name: str = "update_postit"
    description: str = dedent(
        """
        Partial update of a post-it. Only supplied fields are changed.

        - To unlink a notebook, set `notebook_short_id` to null.
        - Position changes are immediately visible in the canvas (animated).
        """
    ).strip()
    args_schema: type[BaseModel] = UpdatePostItArgs

    async def _arun_impl(self, args: dict[str, Any]) -> dict[str, Any]:
        # Keep keys whose value is not None, EXCEPT keep notebook_short_id even if None (sentinel "unlink").
        kwargs = {k: v for k, v in args.items() if v is not None or k == "notebook_short_id"}
        short_id = kwargs.pop("short_id")

        def _do_update() -> dict[str, Any]:
            postit = service.update_postit(team=self._team, user=self._user, short_id=short_id, **kwargs)
            return _postit_dict(postit)

        return await sync_to_async(_do_update)()


# ---- delete_postit ----


class DeletePostItArgs(BaseModel):
    short_id: str = Field(description="The post-it to delete")


class DeletePostItTool(MaxTool):
    name: str = "delete_postit"
    description: str = dedent(
        """
        Soft-delete a post-it. All its incoming and outgoing edges are removed.
        """
    ).strip()
    args_schema: type[BaseModel] = DeletePostItArgs

    async def _arun_impl(self, args: dict[str, Any]) -> dict[str, Any]:
        await sync_to_async(service.delete_postit)(
            team=self._team,
            user=self._user,
            short_id=args["short_id"],
        )
        return {"ok": True}


# ---- connect_postits ----


class ConnectPostItsArgs(BaseModel):
    source_short_id: str = Field(description="Arrow tail post-it")
    target_short_id: str = Field(description="Arrow head post-it")


class ConnectPostItsTool(MaxTool):
    name: str = "connect_postits"
    description: str = dedent(
        """
        Draw a directed arrow from `source` to `target`.

        Idempotent: calling twice with the same source/target returns success without creating duplicates.
        Self-loops (source == target) are rejected.
        """
    ).strip()
    args_schema: type[BaseModel] = ConnectPostItsArgs

    async def _arun_impl(self, args: dict[str, Any]) -> dict[str, Any]:
        source_short_id = args["source_short_id"]
        target_short_id = args["target_short_id"]

        def _do_connect() -> None:
            service.connect(
                team=self._team,
                user=self._user,
                source_short_id=source_short_id,
                target_short_id=target_short_id,
            )

        await sync_to_async(_do_connect)()
        return {"source": source_short_id, "target": target_short_id}


# ---- disconnect_postits ----


class DisconnectPostItsArgs(BaseModel):
    source_short_id: str = Field(description="Arrow tail")
    target_short_id: str = Field(description="Arrow head")


class DisconnectPostItsTool(MaxTool):
    name: str = "disconnect_postits"
    description: str = dedent(
        """
        Remove the arrow from `source` to `target`. No-op if no such arrow exists.
        """
    ).strip()
    args_schema: type[BaseModel] = DisconnectPostItsArgs

    async def _arun_impl(self, args: dict[str, Any]) -> dict[str, Any]:
        await sync_to_async(service.disconnect)(
            team=self._team,
            user=self._user,
            source_short_id=args["source_short_id"],
            target_short_id=args["target_short_id"],
        )
        return {"ok": True}


# ---- link_notebook_to_postit ----


class LinkNotebookArgs(BaseModel):
    postit_short_id: str = Field(description="The post-it to update")
    notebook_short_id: str | None = Field(
        description="Notebook short_id to link to, or null to unlink",
    )


class LinkNotebookToPostItTool(MaxTool):
    name: str = "link_notebook_to_postit"
    description: str = dedent(
        """
        Attach a notebook to a post-it (or unlink by passing null).

        Validates that the notebook exists in the same team. Clicking the post-it in the UI navigates to the linked notebook.
        """
    ).strip()
    args_schema: type[BaseModel] = LinkNotebookArgs

    async def _arun_impl(self, args: dict[str, Any]) -> dict[str, Any]:
        postit_short_id = args["postit_short_id"]
        notebook_short_id = args["notebook_short_id"]

        def _do_link() -> dict[str, Any]:
            postit = service.update_postit(
                team=self._team,
                user=self._user,
                short_id=postit_short_id,
                notebook_short_id=notebook_short_id,
            )
            return _postit_dict(postit)

        return await sync_to_async(_do_link)()
