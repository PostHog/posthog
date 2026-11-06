from django.db import models

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import UUIDModel

from products.workflows.backend.facade.enums import (
    InboundEmailContentStatus,
    InboundEmailDomainKind,
    InboundEmailDomainStatus,
    ReceivedEmailFilterReason,
    ReceivedEmailMatchMethod,
    ReceivedEmailStatus,
)


class InboundEmailDomain(TeamScopedRootMixin, UUIDModel):
    """A domain whose mail belongs to one team.

    An SES sending identity can be shared by the teams of an organization, so it can't say which of them owns
    incoming mail. This row does, and mail to a domain with no active row is dropped.
    """

    Kind = InboundEmailDomainKind
    Status = InboundEmailDomainStatus

    # db_constraint=False: a real FK to a hot parent table takes a parent-table lock on creation.
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False, related_name="+")
    domain = models.CharField(max_length=253)
    kind = models.CharField(max_length=16, choices=InboundEmailDomainKind.choices)
    status = models.CharField(max_length=16, choices=InboundEmailDomainStatus.choices)
    mx_checked_at = models.DateTimeField(null=True, blank=True)
    activated_at = models.DateTimeField(null=True, blank=True)
    # An active domain keeps receiving through a brief DNS or SES problem, so it is only demoted once this gets old.
    checks_failing_since = models.DateTimeField(null=True, blank=True)
    # When the team last went over its daily cap, so the view can say mail was dropped.
    daily_limit_reached_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        "posthog.User", on_delete=models.SET_NULL, null=True, blank=True, db_constraint=False, related_name="+"
    )

    class Meta:
        constraints = [
            # Several teams may try a domain, but only one can hold it, and proving the MX is what takes it.
            models.UniqueConstraint(
                fields=["domain"],
                condition=models.Q(status="active"),
                name="workflows_inbound_domain_one_active",
            ),
            models.UniqueConstraint(fields=["team", "domain"], name="workflows_inbound_domain_team_unique"),
            models.UniqueConstraint(
                fields=["team"],
                condition=models.Q(kind="generated"),
                name="workflows_inbound_domain_one_generated",
            ),
        ]
        indexes = [models.Index(fields=["domain"], name="workflows_inbound_domain_idx")]


class ReceivedEmail(TeamScopedRootMixin, UUIDModel):
    """One message as one team sees it: `envelope_recipients` holds only that team's addresses.

    The body, headers and attachments stay in object storage, so this table holds nothing a search doesn't need.
    The primary key derives from the team and the SES message ID, so a redelivery lands on the same row.
    """

    Status = ReceivedEmailStatus
    FilterReason = ReceivedEmailFilterReason
    ContentStatus = InboundEmailContentStatus

    # db_constraint=False: a real FK to a hot parent table takes a parent-table lock on creation.
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False, related_name="+")
    domain = models.ForeignKey(InboundEmailDomain, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    ses_message_id = models.CharField(max_length=128)
    message_id = models.CharField(max_length=512, blank=True, default="")
    in_reply_to = models.CharField(max_length=512, blank=True, default="")

    from_address = models.CharField(max_length=320, blank=True, default="")
    from_name = models.CharField(max_length=320, blank=True, default="")
    envelope_from = models.CharField(max_length=320, blank=True, default="")
    subject = models.CharField(max_length=1000, blank=True, default="")
    to_addresses = models.JSONField(default=list, blank=True)
    cc_addresses = models.JSONField(default=list, blank=True)
    reply_to_addresses = models.JSONField(default=list, blank=True)
    envelope_recipients = models.JSONField(default=list, blank=True)

    spf_verdict = models.CharField(max_length=32, blank=True, default="")
    dkim_verdict = models.CharField(max_length=32, blank=True, default="")
    dmarc_verdict = models.CharField(max_length=32, blank=True, default="")
    spam_verdict = models.CharField(max_length=32, blank=True, default="")
    virus_verdict = models.CharField(max_length=32, blank=True, default="")
    sender_verified = models.BooleanField(default=False)
    auto_submitted = models.BooleanField(default=False)

    # Set only for a sender whose domain was proved, so a forged From can't link mail to someone else's person.
    person_id = models.UUIDField(null=True, blank=True)
    person_distinct_id = models.CharField(max_length=400, blank=True, default="")
    # The send this answers, when its In-Reply-To or References name one of the team's sends.
    original_message_id = models.UUIDField(null=True, blank=True)
    original_workflow_id = models.UUIDField(null=True, blank=True)
    match_method = models.CharField(max_length=16, choices=ReceivedEmailMatchMethod.choices, blank=True, default="")

    status = models.CharField(max_length=16, choices=ReceivedEmailStatus.choices)
    filter_reason = models.CharField(max_length=32, choices=ReceivedEmailFilterReason.choices, blank=True, default="")
    content_status = models.CharField(max_length=16, choices=InboundEmailContentStatus.choices)
    size_bytes = models.BigIntegerField(default=0)
    attachment_count = models.IntegerField(default=0)

    received_at = models.DateTimeField()
    event_captured_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["team", "ses_message_id"], name="workflows_received_email_one_per_team"),
        ]
        indexes = [
            models.Index(fields=["team", "-received_at"], name="workflows_received_email_list"),
            models.Index(fields=["received_at"], name="workflows_received_email_age"),
        ]
