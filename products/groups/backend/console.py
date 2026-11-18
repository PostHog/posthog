import json
from datetime import UTC, datetime

from django import forms
from django.contrib import messages
from django.db.models import Model
from django.http import HttpRequest, HttpResponse
from django.utils.dateparse import parse_datetime

from posthog.admin.console.panels import Fact, Operation, Owner, Panel
from posthog.admin.console.registry import console
from posthog.admin.console.tools import Cell, Notice, Page, Row, Table
from posthog.constants import GROUP_TYPES_LIMIT
from posthog.models.team.team import Team

from products.groups.backend.facade import api
from products.groups.backend.facade.contracts import (
    GroupType,
    GroupTypeChanged,
    GroupTypeEdit,
    GroupTypeNotFound,
    GroupTypesUnavailable,
)

PRODUCT_ANALYTICS = Owner(name="Product analytics", crest="product-analytics")
NOT_SET = "Not set"
FIELD_LABELS = {
    "name_singular": "Singular name",
    "name_plural": "Plural name",
    "default_columns": "Default columns",
    "created_at": "Created (UTC)",
}
CREATED_AT_EFFECT = "Queries leave this group off events from before the created time."
CHANGED_SINCE_READ = "This group type changed since you opened this form. Go back and open the edit again to review it."


def format_created_at(value: datetime | None) -> str:
    # Milliseconds, like personhog stores it, so a form that staff submit unchanged matches the stored value.
    return value.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3] if value else ""


class EditGroupTypeForm(forms.Form):
    name_singular = forms.CharField(label=FIELD_LABELS["name_singular"], required=False)
    name_plural = forms.CharField(label=FIELD_LABELS["name_plural"], required=False)
    default_columns = forms.CharField(
        label=FIELD_LABELS["default_columns"],
        required=False,
        help_text='A JSON list of column names, for example ["name", "email"]. Leave it empty to clear the columns.',
    )
    created_at = forms.CharField(
        label=FIELD_LABELS["created_at"],
        required=False,
        help_text=f"For example 2026-01-15 10:30:00. {CREATED_AT_EFFECT} Leave it empty to keep the group on every event.",
    )
    reason = forms.CharField(widget=forms.Textarea(attrs={"rows": 3}), help_text="Goes into the audit log.")
    # The group type as staff saw it when the form opened. The confirmation token carries it to the save.
    baseline = forms.CharField(widget=forms.HiddenInput)

    def clean_default_columns(self) -> list[str] | None:
        raw = self.cleaned_data["default_columns"].strip()
        if not raw:
            return None
        try:
            columns = json.loads(raw)
        except json.JSONDecodeError:
            columns = None
        if not isinstance(columns, list) or not all(isinstance(column, str) for column in columns):
            raise forms.ValidationError('Enter a JSON list of column names, for example ["name", "email"].')
        return columns

    def clean_created_at(self) -> datetime | None:
        raw = self.cleaned_data["created_at"].strip()
        if not raw:
            return None
        # parse_datetime returns None for text that is not a date, and raises ValueError for an impossible date.
        try:
            parsed = parse_datetime(raw)
        except ValueError:
            parsed = None
        if parsed is None:
            raise forms.ValidationError("Enter a date and time, for example 2026-01-15 10:30:00.")
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        # Personhog keeps milliseconds, so finer input would differ from the stored value on every save.
        return parsed.replace(microsecond=parsed.microsecond // 1000 * 1000)

    def edit(self) -> GroupTypeEdit:
        return GroupTypeEdit(
            name_singular=self.cleaned_data["name_singular"].strip(),
            name_plural=self.cleaned_data["name_plural"].strip(),
            default_columns=self.cleaned_data["default_columns"],
            created_at=self.cleaned_data["created_at"],
        )


def _display_values(item: GroupType | GroupTypeEdit) -> dict[str, str]:
    created_at = format_created_at(item.created_at)
    return {
        "name_singular": item.name_singular or NOT_SET,
        "name_plural": item.name_plural or NOT_SET,
        "default_columns": json.dumps(item.default_columns) if item.default_columns is not None else NOT_SET,
        "created_at": created_at or NOT_SET,
    }


def _describe(group_type: GroupType) -> str:
    names = f"{group_type.name_singular or 'no singular name'} / {group_type.name_plural or 'no plural name'}"
    if group_type.created_at is None:
        return f"{names}, no created time"
    return f"{names}, created {format_created_at(group_type.created_at)} UTC"


class GroupTypeEditor:
    """The preview and the save of the edit operation for the group type at one index."""

    def __init__(self, index: int) -> None:
        self.index = index

    def preview(self, request: HttpRequest, obj: Model, form: forms.Form) -> Page:
        assert isinstance(obj, Team) and isinstance(form, EditGroupTypeForm)
        try:
            current = api.get_group_type(obj.project_id, self.index)
        except GroupTypeNotFound:
            form.add_error(None, f"This project has no group type with index {self.index} anymore.")
            return Page(blocks=())
        except GroupTypesUnavailable:
            form.add_error(None, "Could not load the group type from personhog. Try again.")
            return Page(blocks=())
        if api.group_type_fingerprint(current) != form.cleaned_data["baseline"]:
            form.add_error(None, CHANGED_SINCE_READ)
            return Page(blocks=())
        edit = form.edit()
        fields = api.group_type_changes(current, edit)
        if not fields:
            form.add_error(None, "Nothing changed. Edit a field to save, or go back.")
            return Page(blocks=())
        before, after = _display_values(current), _display_values(edit)
        rows = tuple(
            Row(cells=(Cell(text=FIELD_LABELS[field]), Cell(text=before[field]), Cell(text=after[field])))
            for field in fields
        )
        return Page(
            blocks=(
                Table(columns=("Field", "Now", "After saving"), rows=rows),
                *((Notice(text=CREATED_AT_EFFECT),) if "created_at" in fields else ()),
            )
        )

    def save(self, request: HttpRequest, obj: Model, form: forms.Form | None) -> HttpResponse | None:
        assert isinstance(obj, Team) and isinstance(form, EditGroupTypeForm)
        edit = form.edit()
        try:
            previous = api.update_group_type(obj.project_id, self.index, edit, form.cleaned_data["baseline"])
        except GroupTypeChanged:
            messages.error(request, CHANGED_SINCE_READ)
            return HttpResponse(status=409)
        except GroupTypeNotFound:
            messages.error(request, f"This project has no group type with index {self.index} anymore.")
            return HttpResponse(status=404)
        except GroupTypesUnavailable:
            messages.error(request, "Could not save the group type, because personhog did not answer. Try again.")
            return HttpResponse(status=503)
        fields = api.group_type_changes(previous, edit)
        if not fields:
            messages.info(request, "Nothing changed, so nothing was saved.")
            return None
        before, after = _display_values(previous), _display_values(edit)
        changes = "; ".join(f"{FIELD_LABELS[field]}: {before[field]} to {after[field]}" for field in fields)
        messages.success(request, f"Saved group type {self.index} for team '{obj.name}'. {changes}.")
        return None


@console.register_panel
class GroupTypesPanel(Panel):
    record = "team"
    key = "group-types"
    title = "Group types"
    owner = PRODUCT_ANALYTICS
    operation_keys = frozenset(f"edit-{index}" for index in range(GROUP_TYPES_LIMIT))

    def facts(self, obj: Model) -> list[Fact]:
        assert isinstance(obj, Team)
        try:
            group_types = api.list_group_types(obj.project_id)
        except GroupTypesUnavailable:
            return [
                Fact(label="Group types", value="Could not load them from personhog. Reload the page to try again.")
            ]
        if not group_types:
            return [Fact(label="Group types", value="None yet")]
        return [
            Fact(label=f"{group_type.index}: {group_type.group_type}", value=_describe(group_type))
            for group_type in group_types
        ]

    def operations(self, obj: Model) -> list[Operation]:
        assert isinstance(obj, Team)
        try:
            group_types = api.list_group_types(obj.project_id)
        except GroupTypesUnavailable:
            return []
        return [self._edit(group_type) for group_type in group_types]

    def _edit(self, group_type: GroupType) -> Operation:
        editor = GroupTypeEditor(group_type.index)
        return Operation(
            key=f"edit-{group_type.index}",
            label=f"Edit {group_type.group_type}",
            handler=editor.save,
            preview=editor.preview,
            danger=True,
            form_class=EditGroupTypeForm,
            form_initial={
                "name_singular": group_type.name_singular,
                "name_plural": group_type.name_plural,
                "default_columns": json.dumps(group_type.default_columns)
                if group_type.default_columns is not None
                else "",
                "created_at": format_created_at(group_type.created_at),
                "baseline": api.group_type_fingerprint(group_type),
            },
            description=f"The team sees the new names in the app. {CREATED_AT_EFFECT}",
            undo_hint="To undo, edit the group type again and enter the old values. The message after saving lists them.",
        )


for index in range(GROUP_TYPES_LIMIT):
    console.register_moved_action(
        old_path=f"admin/posthog/team/<int:pk>/group-type-mapping/{index}/edit/",
        record="team",
        target=f"group-types/edit-{index}/",
    )
