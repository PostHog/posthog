import uuid
import ipaddress
from typing import Any

from django import forms
from django.conf import settings
from django.contrib import admin
from django.core.exceptions import PermissionDenied
from django.http import HttpRequest, HttpResponse
from django.template.response import TemplateResponse
from django.urls import URLPattern, path
from django.utils import timezone

from posthog.models import OrganizationMembership, Team, User
from posthog.utils import get_trusted_client_ip

from .facade.enums import Effect, Scope, Surface, TargetType
from .logic.decisions import decide, matching_rules
from .logic.guards import RuleDraft, check_rule
from .logic.impact import preview
from .logic.targets import TARGETS, InvalidTarget, Subject
from .models import SCOPE_LABELS, SecurityRule

SURFACE_LABELS = {
    Surface.SIGNUP: "Signup",
    Surface.APP_ACCESS: "App access and login",
    Surface.AI_GATEWAY: "AI gateway",
}

# Present on the second submit only, so the first submit shows the preview instead of saving.
CONFIRM_FIELD = "_confirm_rule"


class SecurityRuleForm(forms.ModelForm):
    requester_ip: str | None = None

    class Meta:
        model = SecurityRule
        fields = ["target_type", "target_value", "scope", "reason", "expires_at"]
        help_texts = {
            "target_value": (
                "An email address, a domain, an IP address or CIDR range, or an ID. "
                "Any alias works for an email root: the +suffix is dropped when saved."
            ),
            "expires_at": "Leave empty to keep the rule until someone revokes it.",
        }

    def clean(self) -> dict[str, Any]:
        super().clean()
        cleaned = self.cleaned_data
        target_type = cleaned.get("target_type")
        raw_value = cleaned.get("target_value")
        scope = cleaned.get("scope")
        if not target_type or not raw_value or not scope:
            return cleaned

        try:
            value = TARGETS[TargetType(target_type)].normalize(raw_value)
        except InvalidTarget as error:
            self.add_error("target_value", str(error))
            return cleaned
        cleaned["target_value"] = value

        draft = RuleDraft(
            target_type=TargetType(target_type), target_value=value, effect=Effect.BLOCK, scope=Scope(scope)
        )
        for message in check_rule(draft, requester_ip=self.requester_ip):
            self.add_error(None, message)

        # The unique constraint covers effect, which this form sets rather than asks for,
        # so Django's own constraint check skips it and the duplicate would reach the database.
        duplicate = SecurityRule.objects.filter(
            target_type=target_type, target_value=value, effect=Effect.BLOCK, scope=scope, revoked_at__isnull=True
        )
        if duplicate.exists():
            self.add_error(None, "An unrevoked rule already blocks this target with this scope. Revoke it first.")

        expires_at = cleaned.get("expires_at")
        if expires_at is not None and expires_at <= timezone.now():
            self.add_error("expires_at", "Pick a time in the future.")

        return cleaned

    def draft(self) -> RuleDraft:
        return RuleDraft(
            target_type=TargetType(self.cleaned_data["target_type"]),
            target_value=self.cleaned_data["target_value"],
            effect=Effect.BLOCK,
            scope=Scope(self.cleaned_data["scope"]),
        )


class StatusFilter(admin.SimpleListFilter):
    title = "status"
    parameter_name = "status"

    def lookups(self, request: HttpRequest, model_admin: admin.ModelAdmin) -> list[tuple[str, str]]:
        return [("active", "Active"), ("expired", "Expired"), ("revoked", "Revoked")]

    def queryset(self, request: HttpRequest, queryset: Any) -> Any:
        now = timezone.now()
        if self.value() == "active":
            return queryset.active()
        if self.value() == "expired":
            return queryset.filter(revoked_at__isnull=True, expires_at__lte=now)
        if self.value() == "revoked":
            return queryset.filter(revoked_at__isnull=False)
        return queryset


@admin.register(SecurityRule)
class SecurityRuleAdmin(admin.ModelAdmin):
    form = SecurityRuleForm
    list_display = (
        "target",
        "effect",
        "scope",
        "reason",
        "status",
        "expires_at",
        "created_by_email",
        "created_at",
    )
    list_filter = ("effect", "scope", "target_type", StatusFilter)
    search_fields = ("target_value", "reason")
    ordering = ("-created_at",)
    list_select_related = ("created_by",)
    actions = ["revoke_selected"]
    readonly_fields = (
        "target_type",
        "target_value",
        "effect",
        "scope",
        "status",
        "reason",
        "expires_at",
        "created_by",
        "created_at",
        "revoked_at",
        "revoked_by",
    )

    def get_readonly_fields(self, request: HttpRequest, obj: SecurityRule | None = None) -> tuple[str, ...]:
        # The add form edits the draft. A saved rule changes only by being revoked, so its
        # history always describes what was enforced.
        return self.readonly_fields if obj is not None else ()

    def get_fields(self, request: HttpRequest, obj: SecurityRule | None = None) -> tuple[str, ...]:
        if obj is None:
            return tuple(SecurityRuleForm.Meta.fields)
        return self.readonly_fields

    def has_change_permission(self, request: HttpRequest, obj: SecurityRule | None = None) -> bool:
        return False

    def has_delete_permission(self, request: HttpRequest, obj: SecurityRule | None = None) -> bool:
        return False

    def get_form(
        self, request: HttpRequest, obj: SecurityRule | None = None, change: bool = False, **kwargs: Any
    ) -> type[forms.ModelForm]:
        if obj is not None:
            # The help texts tell someone filling in the add form what to type. On a saved
            # rule every field is read-only, so they would describe inputs that aren't there.
            kwargs["help_texts"] = {}
        form_class = super().get_form(request, obj, change=change, **kwargs)
        requester_ip = get_trusted_client_ip(request)

        class RequestAwareForm(form_class):  # type: ignore[valid-type,misc]
            def __init__(self, *args: Any, **form_kwargs: Any) -> None:
                super().__init__(*args, **form_kwargs)
                self.requester_ip = requester_ip

        return RequestAwareForm

    def changelist_view(self, request: HttpRequest, extra_context: dict[str, Any] | None = None) -> HttpResponse:
        # Without change permission Django titles the list "Select security rule to view".
        return super().changelist_view(request, {"title": "Security rules", **(extra_context or {})})

    def add_view(
        self, request: HttpRequest, form_url: str = "", extra_context: dict[str, Any] | None = None
    ) -> HttpResponse:
        if request.method == "POST" and CONFIRM_FIELD not in request.POST:
            form = self.get_form(request)(request.POST)
            if form.is_valid():
                return self._confirm_response(request, form)
        return super().add_view(request, form_url, extra_context)

    def render_change_form(
        self,
        request: HttpRequest,
        context: dict[str, Any],
        add: bool = False,
        change: bool = False,
        form_url: str = "",
        obj: SecurityRule | None = None,
    ) -> HttpResponse:
        # Every submit of the add form goes to the preview first, so the variants that
        # promise to save and continue would act exactly like the plain submit.
        context.update({"show_save_and_add_another": False, "show_save_and_continue": False})
        return super().render_change_form(request, context, add, change, form_url, obj)

    def save_model(self, request: HttpRequest, obj: SecurityRule, form: forms.ModelForm, change: bool) -> None:
        if not change:
            obj.effect = Effect.BLOCK
            obj.created_by = request.user if isinstance(request.user, User) else None
        super().save_model(request, obj, form, change)

    @admin.action(description="Revoke selected rules")
    def revoke_selected(self, request: HttpRequest, queryset: Any) -> None:
        revoked = 0
        for rule in queryset.filter(revoked_at__isnull=True):
            rule.revoked_at = timezone.now()
            rule.revoked_by = request.user if isinstance(request.user, User) else None
            rule.save(update_fields=["revoked_at", "revoked_by"])
            self.log_change(request, rule, "Revoked")
            revoked += 1
        self.message_user(request, f"Revoked {revoked} rule{'s' if revoked != 1 else ''}.")

    def get_urls(self) -> list[URLPattern]:
        return [
            path("lookup/", self.admin_site.admin_view(self.lookup_view), name="security_securityrule_lookup"),
            *super().get_urls(),
        ]

    def lookup_view(self, request: HttpRequest) -> HttpResponse:
        if not self.has_view_permission(request):
            raise PermissionDenied
        query = request.GET.get("q", "").strip()
        context: dict[str, Any] = {
            **self.admin_site.each_context(request),
            "opts": self.model._meta,
            "title": "Look up",
            "query": query,
            "region": _region_label(),
        }
        subject_and_reading = subject_from_query(query) if query else None
        if query and subject_and_reading is None:
            context["unreadable"] = True
        elif subject_and_reading is not None:
            subject, read_as = subject_and_reading
            context["read_as"] = read_as
            context["matches"] = [_rule_row(rule) for rule in matching_rules(subject)]
            context["decisions"] = [
                {
                    "surface": SURFACE_LABELS[decision.surface],
                    "blocked": decision.blocked,
                    "rule": _rule_row(decision.deciding_rule) if decision.deciding_rule else None,
                }
                for decision in decide(subject)
            ]
        return TemplateResponse(request, "admin/security/securityrule/lookup.html", context)

    def _confirm_response(self, request: HttpRequest, form: forms.ModelForm) -> HttpResponse:
        draft = form.draft()  # type: ignore[attr-defined]
        context = {
            **self.admin_site.each_context(request),
            "opts": self.model._meta,
            "title": "Confirm the rule",
            "form": form,
            "confirm_field": CONFIRM_FIELD,
            "target_label": TARGETS[draft.target_type].label,
            "target_value": draft.target_value,
            "scope_label": SCOPE_LABELS[draft.scope],
            "reason": form.cleaned_data["reason"],
            "expires_at": form.cleaned_data.get("expires_at"),
            "impact": preview(draft),
            "region": _region_label(),
        }
        return TemplateResponse(request, "admin/security/securityrule/confirm_add.html", context)

    @admin.display(description="Target", ordering="target_value")
    def target(self, rule: SecurityRule) -> str:
        return f"{rule.get_target_type_display()}: {rule.target_value}"

    @admin.display(description="Status")
    def status(self, rule: SecurityRule) -> str:
        if rule.revoked_at is not None:
            return "Revoked"
        return "Active" if rule.is_active else "Expired"

    @admin.display(description="Created by", ordering="created_by__email")
    def created_by_email(self, rule: SecurityRule) -> str:
        return rule.created_by.email if rule.created_by else "Unknown"


def subject_from_query(query: str) -> tuple[Subject, str] | None:
    """Read a lookup query as the kind of thing it looks like, and say how it was read.

    None when the query reads as none of them.
    """
    if "@" in query:
        user = User.objects.filter(email__iexact=query).first()
        if user is None:
            return Subject.for_account(email=query), "an email address with no account in this region"
        return _subject_for_user(user), "an email address"

    try:
        return Subject(ip=str(ipaddress.ip_address(query))), "an IP address"
    except ValueError:
        pass

    try:
        parsed = uuid.UUID(query)
    except ValueError:
        parsed = None
    if parsed is not None:
        user = User.objects.filter(uuid=parsed).first()
        if user is not None:
            return _subject_for_user(user), "a user ID"
        return Subject(organization_ids=frozenset({str(parsed)})), "an organization ID"

    if query.isdigit():
        return Subject(team_ids=frozenset({int(query)})), "a project ID"

    try:
        domain = TARGETS[TargetType.EMAIL_DOMAIN].normalize(query)
    except InvalidTarget:
        return None
    return Subject(domain=domain), "an email domain"


def _subject_for_user(user: User) -> Subject:
    organization_ids = frozenset(
        str(organization_id)
        for organization_id in OrganizationMembership.objects.filter(user=user).values_list(
            "organization_id", flat=True
        )
    )
    team_ids = frozenset(Team.objects.filter(organization_id__in=organization_ids).values_list("id", flat=True))
    return Subject.for_account(
        email=user.email, user_uuid=str(user.uuid), organization_ids=organization_ids, team_ids=team_ids
    )


def _rule_row(rule: SecurityRule) -> dict[str, Any]:
    return {
        "id": rule.id,
        "target": f"{rule.get_target_type_display()}: {rule.target_value}",
        "effect": rule.get_effect_display(),
        "scope": rule.get_scope_display(),
        "reason": rule.reason,
    }


def _region_label() -> str:
    return f"the {settings.CLOUD_DEPLOYMENT} region" if settings.CLOUD_DEPLOYMENT else "this region"
