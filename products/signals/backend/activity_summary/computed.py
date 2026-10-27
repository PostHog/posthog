"""Exact fields of an activity summary that code computes from the window, with no model call.

Consumers that need ids, such as reviewer assignment or the homepage, read these instead of the prose.
`update_activity_summary` computes them from the full window on every successful update, after the
filters of `render.py`, so automated activity does not reach them either.
"""

import re
import json
import datetime
import dataclasses
from collections import Counter
from collections.abc import Iterable
from typing import Any

from posthog.dataclasses import frozen

from products.signals.backend.activity_summary.render import (
    ACTIVITY_NAME_CHARS,
    SCENE_VIEW_TYPE,
    ActivityItem,
    Product,
    TaskItem,
    ViewItem,
    cap_line,
    clean_text,
    is_auto_named,
    person_activity,
    scene_product,
    scope_of,
    scope_product,
    task_units,
)

# Bump on any change to the shape or the meaning of a field, so a consumer can tell old rows apart.
COMPUTED_SCHEMA_VERSION = 1
MAX_OWNED = 20
MAX_WATCHED = 20
# An object opened on fewer days than this is a visit, not something the person keeps an eye on.
MIN_WATCHED_OPEN_DAYS = 3
# The file system refers to these by short id, the activity log by primary key.
_SHORT_ID_SCOPES: frozenset[str] = frozenset({"Insight", "Notebook", "SessionRecordingPlaylist"})

_SNAKE_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")
_TAG_SEPARATORS = re.compile(r"[\s/-]+")


@frozen
class OwnedObject:
    ref: str
    type: str
    id: str
    name: str
    edit_days: int
    last_at: str
    created: bool


@frozen
class WatchedObject:
    ref: str
    type: str
    id: str
    name: str
    open_days: int
    last_at: str
    not_theirs: bool


@frozen
class PageVisits:
    ref: str
    product: str
    open_days: int
    last_at: str


@frozen
class ProductSplit:
    works_in: tuple[str, ...]
    visits: tuple[str, ...]


@frozen
class ComputedFields:
    schema_version: int
    owned: tuple[OwnedObject, ...]
    watched: tuple[WatchedObject, ...]
    pages: tuple[PageVisits, ...]
    products: ProductSplit
    task_count: int

    def as_json(self) -> dict[str, Any]:
        # JSON has no tuples, so the stored value and this one compare equal.
        return json.loads(json.dumps(dataclasses.asdict(self)))


def _day(at: datetime.datetime) -> datetime.date:
    return at.astimezone(datetime.UTC).date()


def _snake(scope: str) -> str:
    """The file system type of an activity log scope, such as "feature_flag" for "FeatureFlag"."""
    return _SNAKE_BOUNDARY.sub("_", scope).lower()


def _name(name: str) -> str:
    return cap_line(clean_text(name, ACTIVITY_NAME_CHARS * 2), ACTIVITY_NAME_CHARS)


def _tag_product(tag: str) -> Product | None:
    key = _TAG_SEPARATORS.sub("_", tag.strip().lower())
    return Product(key) if key in Product._value2member_map_ else None


def _object_id(item: ActivityItem) -> str | None:
    if item.scope in _SHORT_ID_SCOPES and item.short_id:
        return item.short_id
    return item.item_id


def _ranked(counts: Counter[Product]) -> tuple[str, ...]:
    return tuple(str(product) for product, _ in sorted(counts.items(), key=lambda pair: (-pair[1], pair[0])))


def compute_fields(
    tasks: Iterable[TaskItem], activity: Iterable[ActivityItem], views: Iterable[ViewItem]
) -> ComputedFields:
    """The owned and watched objects, the product pages, the products and the task count of one window.

    `owned` holds the objects the person created or changed, the most edited first. `watched` holds
    the objects opened on `MIN_WATCHED_OPEN_DAYS` or more days, the most opened first. A product is in
    `works_in` when the person changed something in it or tagged a task with it, and in `visits` when
    they only opened its pages or objects."""
    kept, _ = person_activity(activity, Counter(), keep_ticket_bursts=True)
    edits: dict[tuple[str, str], list[ActivityItem]] = {}
    work_days: dict[Product, set[datetime.date]] = {}
    for item in kept:
        if (product := scope_product(item.scope)) is not None:
            work_days.setdefault(product, set()).add(_day(item.at))
        if object_id := _object_id(item):
            edits.setdefault((item.scope, object_id), []).append(item)
    work: Counter[Product] = Counter({product: len(days) for product, days in work_days.items()})

    owned_ranked = sorted(
        edits.items(),
        key=lambda entry: (
            -len({_day(row.at) for row in entry[1]}),
            -max(row.at for row in entry[1]).timestamp(),
            entry[0],
        ),
    )
    owned: list[OwnedObject] = []
    for (scope, item_id), rows in owned_ranked[:MAX_OWNED]:
        latest = max(rows, key=lambda row: row.at)
        owned.append(
            OwnedObject(
                ref=f"o{len(owned) + 1}",
                type=_snake(scope),
                id=item_id,
                name=_name(latest.name or ""),
                edit_days=len({_day(row.at) for row in rows}),
                last_at=_day(latest.at).isoformat(),
                created=any(row.activity == "created" for row in rows),
            )
        )

    tasks = list(tasks)
    for task in tasks:
        for tag in task.tags:
            if (product := _tag_product(tag)) is not None:
                work[product] += 1

    visit: Counter[Product] = Counter()
    pages: dict[Product, tuple[datetime.datetime, set[datetime.date]]] = {}
    candidates: list[ViewItem] = []
    for view in views:
        if view.type == SCENE_VIEW_TYPE:
            if (product := scene_product(view.ref)) is not None:
                at, days = pages.get(product, (view.at, set()))
                pages[product] = (max(at, view.at), days | set(view.days))
            continue
        name = (view.name or "").strip()
        if not name or is_auto_named(name):
            continue
        open_days = len(set(view.days))
        if (product := scope_product(scope_of(view.type))) is not None:
            visit[product] += open_days
        if open_days >= MIN_WATCHED_OPEN_DAYS:
            candidates.append(view)
    for product, (_, days) in pages.items():
        visit[product] += len(days)

    candidates.sort(key=lambda view: (-len(set(view.days)), -view.at.timestamp(), view.type, view.ref))
    refs = {(entry.type, entry.id): entry.ref for entry in owned}
    watched: list[WatchedObject] = []
    for view in candidates[:MAX_WATCHED]:
        if (view.type, view.ref) not in refs:
            refs[(view.type, view.ref)] = f"o{len(refs) + 1}"
        watched.append(
            WatchedObject(
                ref=refs[(view.type, view.ref)],
                type=view.type,
                id=view.ref,
                name=_name(view.name or ""),
                open_days=len(set(view.days)),
                last_at=_day(view.at).isoformat(),
                not_theirs=view.not_theirs,
            )
        )
    page_list = [
        PageVisits(ref=f"p{index + 1}", product=str(product), open_days=len(days), last_at=_day(at).isoformat())
        for index, (product, (at, days)) in enumerate(
            sorted(pages.items(), key=lambda entry: (-len(entry[1][1]), -entry[1][0].timestamp(), entry[0]))
        )
    ]
    visits_only = Counter({product: count for product, count in visit.items() if product not in work})
    return ComputedFields(
        schema_version=COMPUTED_SCHEMA_VERSION,
        owned=tuple(owned),
        watched=tuple(watched),
        pages=tuple(page_list),
        products=ProductSplit(works_in=_ranked(work), visits=_ranked(visits_only)),
        task_count=len(task_units(tasks, Counter())),
    )
