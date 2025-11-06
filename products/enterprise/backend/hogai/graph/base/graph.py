from abc import ABC, abstractmethod
from collections.abc import Callable
from functools import wraps
from typing import TYPE_CHECKING, Any, Generic, Literal, TypeVar

from langgraph.graph.state import StateGraph

from posthog.models import Team, User

from products.enterprise.backend.hogai.django_checkpoint.checkpointer import DjangoCheckpointer
from products.enterprise.backend.hogai.utils.types.base import (
    AssistantGraphName,
    AssistantNodeName,
    NodePath,
    PartialStateType,
    StateType,
)

from .context import get_node_path, set_node_path
from .node import BaseAssistantNode

if TYPE_CHECKING:
    from products.enterprise.backend.hogai.utils.types.composed import MaxNodeName


# Base checkpointer for all graphs
global_checkpointer = DjangoCheckpointer()

T = TypeVar("T")


def with_node_path(func: Callable[..., T]) -> Callable[..., T]:
    @wraps(func)
    def wrapper(self, *args: Any, **kwargs: Any) -> T:
        with set_node_path(self.node_path):
            return func(self, *args, **kwargs)

    return wrapper


class BaseAssistantGraph(Generic[StateType, PartialStateType], ABC):
    _team: Team
    _user: User
    _graph: StateGraph
    _node_path: tuple[NodePath, ...]

    def __init__(
        self,
        team: Team,
        user: User,
    ):
        self._team = team
        self._user = user
        self._has_start_node = False
        self._graph = StateGraph(self.state_type)
        self._node_path = (*(get_node_path() or ()), NodePath(name=self.graph_name.value))

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        # Wrap all public methods with the node path context
        for name, method in cls.__dict__.items():
            if callable(method) and not name.startswith("_") and name not in ("graph_name", "state_type", "node_path"):
                setattr(cls, name, with_node_path(method))

    @property
    @abstractmethod
    def state_type(self) -> type[StateType]: ...

    @property
    @abstractmethod
    def graph_name(self) -> AssistantGraphName: ...

    @property
    def node_path(self) -> tuple[NodePath, ...]:
        return self._node_path

    def add_edge(self, from_node: "MaxNodeName", to_node: "MaxNodeName"):
        if from_node == AssistantNodeName.START:
            self._has_start_node = True
        self._graph.add_edge(from_node, to_node)
        return self

    def add_node(self, node: "MaxNodeName", action: BaseAssistantNode[StateType, PartialStateType]):
        self._graph.add_node(node, action)
        return self

    def compile(self, checkpointer: DjangoCheckpointer | None | Literal[False] = None):
        if not self._has_start_node:
            raise ValueError("Start node not added to the graph")
        # TRICKY: We check `is not None` because False has a special meaning of "no checkpointer", which we want to pass on
        compiled_graph = self._graph.compile(
            checkpointer=checkpointer if checkpointer is not None else global_checkpointer
        )
        return compiled_graph
