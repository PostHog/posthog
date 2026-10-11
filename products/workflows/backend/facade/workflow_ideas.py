"""Whole workflows PostHog suggests to a project, and what a person does with them."""

from products.workflows.backend.services.workflow_ideas import (
    accept_idea,
    create_ideas,
    dismiss_idea,
    list_open_ideas,
    mark_viewed,
)

__all__ = [
    "accept_idea",
    "create_ideas",
    "dismiss_idea",
    "list_open_ideas",
    "mark_viewed",
]
