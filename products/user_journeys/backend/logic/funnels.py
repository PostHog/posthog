"""Turn a journey into the funnel that measures how many sessions complete it."""

from posthog.schema import (
    ElementPropertyFilter,
    EventPropertyFilter,
    EventsNode,
    FunnelConversionWindowTimeUnit,
    FunnelsFilter,
    FunnelsQuery,
    Key10,
    PropertyOperator,
    StepOrderValue,
)

from ..facade.contracts import ElementClickStep, Journey, JourneyStep, PageviewStep
from ..facade.enums import UrlMatching

_URL_OPERATORS: dict[UrlMatching, PropertyOperator] = {
    UrlMatching.EXACT: PropertyOperator.EXACT,
    UrlMatching.CONTAINS: PropertyOperator.ICONTAINS,
    UrlMatching.REGEX: PropertyOperator.REGEX,
}


def _url_filter(url: str, matching: UrlMatching) -> EventPropertyFilter:
    return EventPropertyFilter(key="$current_url", operator=_URL_OPERATORS[matching], value=url)


def step_to_events_node(step: JourneyStep) -> EventsNode:
    match step:
        case PageviewStep(url=url, url_matching=matching):
            return EventsNode(event="$pageview", properties=[_url_filter(url, matching)])
        case ElementClickStep():
            properties: list[ElementPropertyFilter | EventPropertyFilter] = [
                ElementPropertyFilter(key=Key10.SELECTOR, operator=PropertyOperator.EXACT, value=step.selector)
            ]
            if step.text is not None:
                properties.append(
                    ElementPropertyFilter(key=Key10.TEXT, operator=PropertyOperator.EXACT, value=step.text)
                )
            if step.href is not None:
                properties.append(
                    ElementPropertyFilter(key=Key10.HREF, operator=PropertyOperator.EXACT, value=step.href)
                )
            if step.url is not None:
                properties.append(_url_filter(step.url, step.url_matching))
            return EventsNode(event="$autocapture", properties=properties)


def _step_label(step: JourneyStep) -> str:
    match step:
        case PageviewStep():
            return f"Pageview of {step.url}"
        case ElementClickStep():
            return f'Click on "{step.text}"' if step.text else f"Click on {step.selector}"


def journey_to_funnels_query(journey: Journey) -> FunnelsQuery:
    return FunnelsQuery(
        # Each funnel step is named after its journey step, so the chart does not read "Autocapture".
        series=[
            step_to_events_node(step).model_copy(update={"custom_name": _step_label(step)}) for step in journey.steps
        ],
        funnelsFilter=FunnelsFilter(
            # A journey is one visit through the product, so each session counts once, not each person.
            funnelAggregateByHogQL="properties.$session_id",
            funnelOrderType=StepOrderValue.ORDERED,
            funnelWindowInterval=journey.conversion_window_minutes,
            funnelWindowIntervalUnit=FunnelConversionWindowTimeUnit.MINUTE,
        ),
    )
