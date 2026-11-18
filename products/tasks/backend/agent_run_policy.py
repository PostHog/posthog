from typing import Any

from posthog.dataclasses import frozen

from products.tasks.backend.facade.profiles import AgentPolicy, EndsRun

WEB_CLIENT_PROVENANCE = "posthog_web"

_AGENT_POLICY_BY_ORIGIN: dict[str, AgentPolicy] = {
    "review_hog": AgentPolicy(ends_run=EndsRun.CALLER),
    "scout_suggestions": AgentPolicy(ends_run=EndsRun.CALLER),
    "workflow": AgentPolicy(ends_run=EndsRun.ON_REQUEST, finish_report_required=True),
    "task_analysis": AgentPolicy(report_activity_tool=True),
    "knowledge_writer": AgentPolicy(branch_push_without_pr=True),
    "user_created": AgentPolicy(pr_thread_link=True),
    "posthog_ai": AgentPolicy(pr_thread_link=True, web_client_by_default=True, expects_system_prompt=True),
}
_UNKNOWN_ORIGIN_POLICY = AgentPolicy(ends_run=EndsRun.ON_REQUEST)


@frozen
class AgentRunPolicy:
    finish_tool: bool
    finish_report_required: bool
    report_activity_tool: bool
    branch_push_only: bool
    expects_system_prompt: bool
    thread_link: bool
    default_client_provenance: str | None


def agent_policy_for_origin(origin_product: str | None) -> AgentPolicy:
    if not origin_product:
        return _UNKNOWN_ORIGIN_POLICY
    return _AGENT_POLICY_BY_ORIGIN.get(origin_product, AgentPolicy())


def resolve_agent_run_policy(policy: AgentPolicy, run_state: dict[str, Any] | None) -> AgentRunPolicy:
    state = run_state or {}
    end_run_when_done = state.get("end_run_when_done") is True
    agent_may_end = policy.ends_run == EndsRun.AGENT or (policy.ends_run == EndsRun.ON_REQUEST and end_run_when_done)
    return AgentRunPolicy(
        finish_tool=agent_may_end and state.get("caller_ends_run") is not True,
        finish_report_required=policy.finish_report_required and end_run_when_done,
        report_activity_tool=policy.report_activity_tool,
        branch_push_only=policy.branch_push_without_pr,
        expects_system_prompt=policy.expects_system_prompt,
        thread_link=policy.pr_thread_link,
        default_client_provenance=WEB_CLIENT_PROVENANCE if policy.web_client_by_default else None,
    )
