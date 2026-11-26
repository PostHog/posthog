from typing import TYPE_CHECKING, Any

from posthog.dataclasses import frozen

from products.tasks.backend.facade.profiles import AgentPolicy, EndsRun

if TYPE_CHECKING:
    from products.tasks.backend.models import Task

WEB_CLIENT_PROVENANCE = "posthog_web"

_AGENT_POLICY_BY_ORIGIN: dict[str, AgentPolicy] = {
    "review_hog": AgentPolicy(ends_run=EndsRun.CALLER),
    "scout_suggestions": AgentPolicy(ends_run=EndsRun.CALLER),
    "workflow": AgentPolicy(ends_run=EndsRun.ON_REQUEST, finish_report_required=True),
    "task_analysis": AgentPolicy(report_activity_tool=True),
    "user_created": AgentPolicy(pr_thread_link=True),
    "posthog_ai": AgentPolicy(pr_thread_link=True, web_client_by_default=True, expects_system_prompt=True),
}
_UNKNOWN_ORIGIN_POLICY = AgentPolicy(ends_run=EndsRun.ON_REQUEST)


@frozen
class AgentRunPolicy:
    finish_tool: bool
    finish_report_required: bool
    report_activity_tool: bool
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
        expects_system_prompt=policy.expects_system_prompt,
        thread_link=policy.pr_thread_link,
        default_client_provenance=WEB_CLIENT_PROVENANCE if policy.web_client_by_default else None,
    )


def task_agent_run_policy(task: "Task", run_state: dict[str, Any] | None) -> AgentRunPolicy:
    profile = task.stored_profile
    policy = profile.agent_policy if profile is not None else agent_policy_for_origin(task.origin_product)
    return resolve_agent_run_policy(policy, run_state)
