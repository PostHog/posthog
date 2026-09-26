import * as research from '@posthog/brand/hoggies/png/research'
import * as stampApproved from '@posthog/brand/hoggies/png/stamp-approved'

import { pngHoggie } from 'lib/brand/hoggies'
import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'

import { WorkflowSuggestionsSwitch } from './WorkflowSuggestionsSwitch'

const HedgehogStampApproved = pngHoggie(stampApproved)
const HedgehogResearch = pngHoggie(research)

const DOCS_URL = 'https://posthog.com/docs/workflows/suggestions'

export function WorkflowSuggestionsIntroduction({ id, enabled }: { id: string; enabled: boolean }): JSX.Element {
    if (!enabled) {
        return (
            <ProductIntroduction
                thingName="suggestion"
                titleOverride="Let PostHog suggest improvements"
                description="PostHog reads how this workflow performs, such as how many people open and click each email, and suggests one concrete change when a step underperforms. Nothing reaches anyone until you approve a suggestion and publish it."
                actionElementOverride={<WorkflowSuggestionsSwitch id={id} />}
                docsURL={DOCS_URL}
                customHog={HedgehogStampApproved}
                hogLayout="responsive"
                useMainContentContainerQueries
            />
        )
    }

    return (
        <ProductIntroduction
            thingName="suggestion"
            titleOverride="Watching this workflow"
            description="PostHog reads this workflow's metrics once a day and files a suggestion here when it finds a change worth making. It waits for a version to collect a couple of days of opens before judging it, so a fresh publish takes a few days to read."
            actionElementOverride={<WorkflowSuggestionsSwitch id={id} />}
            docsURL={DOCS_URL}
            customHog={HedgehogResearch}
            hogLayout="responsive"
            useMainContentContainerQueries
        />
    )
}
