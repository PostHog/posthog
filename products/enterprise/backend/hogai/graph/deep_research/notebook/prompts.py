from products.enterprise.backend.hogai.graph.deep_research.base.prompts import (
    AGENT_INFO,
    INSIGHT_TYPES,
    POSTHOG_CAPABILITIES_PROMPT,
)

DEEP_RESEARCH_NOTEBOOK_PLANNING_PROMPT = (
    AGENT_INFO
    + """

<task>
Create a single-page Markdown plan explaining exactly how you'll answer the research problem.
</task>

<output_template>
# [Research Question Title]

## Understanding the Problem
[Core question and business impact]

## Analysis Approach
1. **[Analysis Name]**: [What to analyze] because [reasoning]
2. **[Analysis Name]**: [What to analyze] because [reasoning]
[Continue for all analyses]

## Key Metrics
- **[Metric]**: [Why it's relevant]
- **[Metric]**: [Why it's relevant]

## Expected Insights
[Patterns and answers we expect to uncover]
</output_template>

<requirements>
- Make it actionable and self-contained
- Expose your reasoning ("I will do X because Y")
- Use business terms, not technical implementation
- Focus on WHAT to analyze, not HOW
- The document will be available to the user
</requirements>

<available_capabilities>
""".strip()
    + "\n\n"
    + POSTHOG_CAPABILITIES_PROMPT
    + "\n\n"
    + INSIGHT_TYPES
    + "\n\n"
    + """
</available_capabilities>

<core_memory>
{core_memory}
</core_memory>
""".strip()
)
