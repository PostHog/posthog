"""
Shared prompts for plan mode used by both chat agent and research agent.
"""

PLANNING_TASK_PROMPT = """
<planning_task>
As a second task, create a single-page notebook plan explaining exactly how you'll accomplish the user's request.

*IMPORTANT*: This notebook should NOT be a draft. The user must be able to see this plan.

<plan_notebook_template>
# [Task Title]

## Understanding the Problem
[Core question/goal and business impact]

## Approach
1. **[Step Name]**: [What to do] because [reasoning]
2. **[Step Name]**: [What to do] because [reasoning]
[Continue for all steps]

## Key Metrics
- **[Metric]**: [Why it's relevant]
- **[Metric]**: [Why it's relevant]

## Expected Outcome
[What we expect to deliver or discover]
</plan_notebook_template>

# Requirements
- Make it actionable and self-contained
- Expose your reasoning ("I will do X because Y")
- Use business terms, not technical implementation
- Focus on WHAT to accomplish, not HOW the tools work
</planning_task>
""".strip()

EXECUTION_CAPABILITIES_PROMPT = """
<execution_capabilities>
After planning, you will switch to execution mode. Here is what will be available:

## Common tools (available in all modes)
{{{default_tools}}}

## Specialized modes (switchable during execution)
{{{available_modes}}}

Use this information to create realistic, actionable plans. Only reference tools and capabilities that are actually available.
</execution_capabilities>
""".strip()
