import contextvars
from contextlib import contextmanager

from products.enterprise.backend.hogai.utils.types.base import NodePath

node_path_context = contextvars.ContextVar[tuple[NodePath, ...]]("node_path_context")


@contextmanager
def set_node_path(node_path: tuple[NodePath, ...]):
    token = node_path_context.set(node_path)
    try:
        yield
    finally:
        node_path_context.reset(token)


def get_node_path() -> tuple[NodePath, ...] | None:
    try:
        return node_path_context.get()
    except LookupError:
        return None
