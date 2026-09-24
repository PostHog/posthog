import json

from django.db import transaction
from django.utils import timezone

from products.notebooks.backend import markdown_collab
from products.notebooks.backend.analytics import NotebookCreationSource, capture_notebook_created, notebook_node_count
from products.notebooks.backend.markdown_conversion import build_markdown_notebook_content
from products.notebooks.backend.models import Notebook

PRODUCT_ANALYTICS_HOME_NOTEBOOK_SHORT_ID = "pa-home-v1"


def _query_block(node_id: str, title: str, query: dict[str, object]) -> str:
    serialized_query = json.dumps(query, separators=(",", ":"))
    return f'<Query nodeId="{node_id}" query={{{serialized_query}}} title="{title}" />'


def _top_events_query_block(event_field: str) -> str:
    return _query_block(
        "top-events",
        "Top events in the last 7 days",
        {
            "kind": "InsightVizNode",
            "source": {
                "kind": "TrendsQuery",
                "dateRange": {"date_from": "-7d", "date_to": None},
                "interval": "day",
                "series": [
                    {
                        "kind": "EventsNode",
                        "event": None,
                        "name": "All events",
                        "math": "total",
                        "custom_name": "Events",
                    }
                ],
                "breakdownFilter": {
                    "breakdown": event_field,
                    "breakdown_type": "event_metadata",
                    "breakdown_limit": 10,
                },
                "trendsFilter": {"display": "ActionsTable"},
            },
            "showHeader": True,
        },
    )


def _initial_markdown() -> str:
    all_events = {"kind": "EventsNode", "event": None, "name": "All events"}
    queries = [
        _query_block(
            "daily-active-users",
            "Daily active users",
            {
                "kind": "InsightVizNode",
                "source": {
                    "kind": "TrendsQuery",
                    "dateRange": {"date_from": "-30d", "date_to": None},
                    "interval": "day",
                    "series": [{**all_events, "math": "dau", "custom_name": "Daily active users"}],
                    "trendsFilter": {"display": "ActionsLineGraph"},
                },
                "showHeader": True,
            },
        ),
        _query_block(
            "event-volume",
            "Event volume",
            {
                "kind": "InsightVizNode",
                "source": {
                    "kind": "TrendsQuery",
                    "dateRange": {"date_from": "-30d", "date_to": None},
                    "interval": "day",
                    "series": [{**all_events, "math": "total", "custom_name": "Events"}],
                    "trendsFilter": {"display": "ActionsLineGraph"},
                },
                "showHeader": True,
            },
        ),
        _query_block(
            "user-retention",
            "User retention",
            {
                "kind": "InsightVizNode",
                "source": {
                    "kind": "RetentionQuery",
                    "retentionFilter": {
                        "period": "Day",
                        "totalIntervals": 8,
                        "targetEntity": {"name": "All events", "type": "events"},
                        "returningEntity": {"name": "All events", "type": "events"},
                        "retentionType": "retention_first_time",
                        "meanRetentionCalculation": "simple",
                    },
                },
                "showHeader": True,
            },
        ),
        _query_block(
            "user-lifecycle",
            "User lifecycle",
            {
                "kind": "InsightVizNode",
                "source": {
                    "kind": "LifecycleQuery",
                    "dateRange": {"date_from": "-12w", "date_to": None},
                    "interval": "week",
                    "series": [all_events],
                },
                "showHeader": True,
            },
        ),
        _top_events_query_block("event"),
    ]
    return "\n\n".join(
        [
            "# Product analytics home",
            "This notebook is shared with everyone in this project. Edit the insights and notes to match your product.",
            *queries,
        ]
    )


def _repair_broken_top_events_query(notebook: Notebook) -> Notebook:
    broken_block = _top_events_query_block("$event")
    fixed_block = _top_events_query_block("event")

    with transaction.atomic():
        locked_notebook = Notebook.objects.select_for_update().get(pk=notebook.pk)
        markdown = markdown_collab.get_markdown_notebook_markdown(locked_notebook.content)
        if markdown is None or broken_block not in markdown:
            return locked_notebook

        repaired_markdown = markdown.replace(broken_block, fixed_block, 1)
        previous_content = locked_notebook.content
        locked_notebook.content = build_markdown_notebook_content(repaired_markdown)
        locked_notebook.text_content = repaired_markdown
        locked_notebook.version += 1
        locked_notebook.last_modified_at = timezone.now()
        locked_notebook.save(update_fields=["content", "text_content", "version", "last_modified_at"])

        update_diff = markdown_collab.build_markdown_update_diff(previous_content, locked_notebook.content)
        transaction.on_commit(
            lambda: markdown_collab.publish_notebook_update(
                locked_notebook.team_id,
                locked_notebook.short_id,
                locked_notebook.version,
                diff=update_diff,
            )
        )
        return locked_notebook


def get_or_create_product_analytics_home_notebook(team_id: int, user_id: int) -> Notebook:
    markdown = _initial_markdown()
    notebook, created = Notebook.objects.get_or_create(
        team_id=team_id,
        short_id=PRODUCT_ANALYTICS_HOME_NOTEBOOK_SHORT_ID,
        defaults={
            "title": "Product analytics home",
            "content": build_markdown_notebook_content(markdown),
            "text_content": markdown,
            "created_by_id": user_id,
            "last_modified_by_id": user_id,
            "visibility": Notebook.Visibility.INTERNAL,
        },
    )
    if notebook.deleted:
        notebook.deleted = False
        notebook.save(update_fields=["deleted"])
    if created:
        capture_notebook_created(
            short_id=notebook.short_id,
            creation_source=NotebookCreationSource.PRODUCT_ANALYTICS_HOME,
            team_id=team_id,
            created_by_id=user_id,
            visibility=notebook.visibility,
            node_count=notebook_node_count(notebook.content),
        )
    return _repair_broken_top_events_query(notebook)
