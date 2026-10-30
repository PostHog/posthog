import * as research from '@posthog/brand/hoggies/png/research'
import * as stampApproved from '@posthog/brand/hoggies/png/stamp-approved'

import { pngHoggie } from 'lib/brand/hoggies'
import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'

const HedgehogStampApproved = pngHoggie(stampApproved)
const HedgehogResearch = pngHoggie(research)

export function WorkflowScoutSuggestionsIntroduction({
    enabled,
    toggle,
}: {
    enabled: boolean
    toggle: JSX.Element
}): JSX.Element {
    return (
        <ProductIntroduction
            thingName="suggestion"
            titleOverride={enabled ? 'Suggestions are on' : 'Let a scout suggest improvements'}
            description={
                enabled
                    ? "A scout with permission to suggest workflow changes files its suggestions here. PostHog's own suggestions cover only email steps, so they won't appear here. Nothing reaches anyone until you approve a suggestion and publish it."
                    : "A scout with permission to suggest workflow changes can file suggestions for this workflow. PostHog's own suggestions cover only email steps, so they won't appear here. Nothing reaches anyone until you approve a suggestion and publish it."
            }
            actionElementOverride={toggle}
            customHog={enabled ? HedgehogResearch : HedgehogStampApproved}
            hogLayout="responsive"
            useMainContentContainerQueries
        />
    )
}
