from textwrap import dedent
from typing import Any

from asgiref.sync import sync_to_async
from pydantic import BaseModel, Field

from posthog.exceptions_capture import capture_exception
from posthog.models import ProxyRecord

from products.platform_features.backend.proxy.diagnostics import diagnose

from ee.hogai.tool import MaxTool

DIAGNOSE_PROXY_TOOL_DESCRIPTION = dedent("""
    Run a deep diagnostic on a managed reverse proxy that's stuck or erroring.

    # When to use
    - User asks why a reverse proxy isn't working / is stuck
    - User mentions an erroring or timed-out proxy
    - User mentions a managed proxy domain by name and reports it's not live
    - The proxy settings page shows a record in 'erroring', 'warning', or 'timed_out' state

    # What it checks
    - Customer DNS CNAME alignment with the expected proxy target
    - Cloudflare custom hostname state (active / pending_validation / pending_issuance / etc.)
    - CAA records walked up the customer's DNS tree (most common stuck-validation cause)
    - HTTP-01 challenge URL reachability and content
    - Live event probe to the customer's proxy domain
    - Certificate expiry

    # Output
    Returns a structured report. Each check has a status (pass / warn / fail / skip) and a
    customer-facing detail string. Failed checks include a remediation block with the exact
    DNS records the customer should add.

    # Identifying the proxy
    - Pass `proxy_record_id` (UUID) when known. The user-visible settings page lists records.
    - When the user names a proxy by domain (e.g. "diagnose e.example.com"), look up the
      record in the contextual `proxy_records` list provided to you and pass its id.
""").strip()


DIAGNOSE_PROXY_CONTEXT_PROMPT_TEMPLATE = """
The user is currently viewing the managed reverse proxy settings. Records on this page:

{proxy_records}

<system_reminder>
When the user asks to diagnose a proxy, pick the matching record's `id` from the list above and
pass it as `proxy_record_id` to `diagnose_proxy`. If the user doesn't specify which proxy, ask
them — only diagnose the one they mean.
</system_reminder>
""".strip()


class DiagnoseProxyToolArgs(BaseModel):
    proxy_record_id: str = Field(
        description="UUID of the ProxyRecord to diagnose. Must belong to the current organization.",
    )


class DiagnoseProxyTool(MaxTool):
    name: str = "diagnose_proxy"
    description: str = DIAGNOSE_PROXY_TOOL_DESCRIPTION
    args_schema: type[BaseModel] = DiagnoseProxyToolArgs
    context_prompt_template: str = DIAGNOSE_PROXY_CONTEXT_PROMPT_TEMPLATE

    # No get_required_resource_access override: diagnose is read-only and the proxy_record
    # lookup in _get_record already filters by the user's organization, which is the actual
    # security boundary. The DRF endpoint requires admin only because its entire viewset is
    # admin-gated (for create/delete/retry mutations), which doesn't apply on the Max path.

    async def _arun_impl(self, proxy_record_id: str) -> tuple[str, dict[str, Any]]:
        try:
            record = await sync_to_async(self._get_record)(proxy_record_id)
        except ProxyRecord.DoesNotExist:
            return f"No reverse proxy with id `{proxy_record_id}` was found in this organization.", {
                "error": "not_found",
                "proxy_record_id": proxy_record_id,
            }

        try:
            report = await sync_to_async(diagnose)(record)
        except Exception as e:
            capture_exception(e, {"team_id": self._team.id, "proxy_record_id": proxy_record_id})
            return f"Diagnose failed unexpectedly: {e}", {
                "error": "diagnose_failed",
                "proxy_record_id": proxy_record_id,
                "details": str(e),
            }

        return _format_report(record, report), _serialize_report(record, report)

    def _get_record(self, proxy_record_id: str) -> ProxyRecord:
        return ProxyRecord.objects.get(id=proxy_record_id, organization_id=self._team.organization_id)


def _format_report(record: ProxyRecord, report: Any) -> str:
    """Build a markdown summary the LLM can directly relay to the user."""
    lines = [f"**Diagnosed `{record.domain}`** — {report.summary.status}"]
    if report.summary.next_action:
        lines.append("")
        lines.append(f"_Next action:_ {report.summary.next_action}")
    lines.append("")
    for check in report.checks:
        marker = {"pass": "✓", "warn": "!", "fail": "×", "skip": "–"}.get(check.status, "?")
        lines.append(f"- {marker} **{check.name}** ({check.status}): {check.detail}")
        if check.remediation:
            lines.append(f"    - _Fix:_ {check.remediation.summary}")
            for dns_record in check.remediation.records:
                lines.append(f"        - `{dns_record.name}  {dns_record.type}  {dns_record.value}`")
    return "\n".join(lines)


def _serialize_report(record: ProxyRecord, report: Any) -> dict[str, Any]:
    """Return the full structured report so downstream UIs can render it."""
    return {
        "proxy_record_id": str(record.id),
        "domain": record.domain,
        "ran_at": report.ran_at.isoformat(),
        "summary": {
            "status": report.summary.status,
            "primary_issue": report.summary.primary_issue,
            "next_action": report.summary.next_action,
        },
        "checks": [
            {
                "id": check.id,
                "name": check.name,
                "status": check.status,
                "detail": check.detail,
                "remediation": (
                    {
                        "type": check.remediation.type,
                        "summary": check.remediation.summary,
                        "records": [
                            {"name": r.name, "type": r.type, "value": r.value} for r in check.remediation.records
                        ],
                    }
                    if check.remediation
                    else None
                ),
            }
            for check in report.checks
        ],
    }
