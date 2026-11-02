"""Local demo data for the Signals inbox. Callers must guard on DEBUG and not cloud."""

from products.signals.backend.inbox_seed import (
    SeededChat as SeededChat,
    SeededInbox as SeededInbox,
    seed_demo_chat as seed_demo_chat,
    seed_demo_inbox as seed_demo_inbox,
)
