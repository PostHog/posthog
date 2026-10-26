from products.workflows.backend.facade.data_suggestions import count_waiting_data_suggestions

from ...facade.enums import HighlightLabel
from ..highlight_rules import exact
from ..highlight_types import Candidate, Context, Found, Source

IDEAS = "{count} workflow ideas based on your events are ready"
IDEA = "1 workflow idea based on your events is ready"
IDEAS_DETAIL = "Pick one to build it as a draft workflow"


def find(context: Context) -> Found:
    count = count_waiting_data_suggestions(team=context.team)
    if not count:
        return Found()
    return Found(
        items=(
            Candidate(
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


SOURCE = Source(name="workflow_ideas", find=find, scopes=("hog_flow:read",))
