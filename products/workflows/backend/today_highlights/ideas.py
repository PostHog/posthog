from products.today.backend.facade.contracts import HighlightCandidate, HighlightContext, HighlightFindings
from products.today.backend.facade.enums import HighlightLabel
from products.today.backend.facade.highlight_helpers import exact
from products.workflows.backend.facade.data_suggestions import count_waiting_data_suggestions

IDEAS = "{count} workflow ideas based on your events are ready"
IDEA = "1 workflow idea based on your events is ready"
IDEAS_DETAIL = "Pick one to build it as a draft workflow"


def find_workflow_ideas(context: HighlightContext) -> HighlightFindings:
    count = count_waiting_data_suggestions(team=context.team, user=context.user)
    if not count:
        return HighlightFindings()
    return HighlightFindings(
        items=(
            HighlightCandidate(
                key="workflow-ideas",
                label=HighlightLabel.OPPORTUNITY,
                family="workflows",
                importance=0.3,
                relevance=1.0,
                title=IDEA if count == 1 else IDEAS.format(count=exact(count)),
                detail=IDEAS_DETAIL,
                url="/workflows",
            ),
        )
    )
