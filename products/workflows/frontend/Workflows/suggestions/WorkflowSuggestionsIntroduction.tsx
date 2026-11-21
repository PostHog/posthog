import * as research from '@posthog/brand/hoggies/png/research'
import * as stampApproved from '@posthog/brand/hoggies/png/stamp-approved'
import { LemonButton } from '@posthog/lemon-ui'

import { pngHoggie } from 'lib/brand/hoggies'
import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { urls } from 'scenes/urls'

import type { SuggestionsScoutStatusEnumApi } from '../../generated/api.schemas'
import { WorkflowSuggestionsSwitch } from './WorkflowSuggestionsSwitch'

const HedgehogStampApproved = pngHoggie(stampApproved)
const HedgehogResearch = pngHoggie(research)

const DOCS_URL = 'https://posthog.com/docs/workflows/suggestions'
export function WorkflowSuggestionsIntroduction({
    id,
    enabled,
    scoutStatus,
}: {
    id: string
    enabled: boolean
    scoutStatus?: SuggestionsScoutStatusEnumApi
}): JSX.Element {
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

    if (scoutStatus === 'dry_run') {
        return (
            <ProductIntroduction
                thingName="suggestion"
                titleOverride="Suggestions are on hold while the workflows scout is in dry run"
                description={`The workflows scout reads this workflow, but in dry run it can't file suggestions. To get suggestions, open the scout's settings and turn on "Write signals to the inbox".`}
                actionElementOverride={
                    <>
                        <LemonButton
                            type="primary"
                            to={urls.inboxScout('signals-scout-workflows')}
                            // pinned: data-attr - autocapture dashboards read it
                            data-attr="workflow-suggestions-scout-dry-run-open"
                        >
                            Open scout settings
                        </LemonButton>
                        <WorkflowSuggestionsSwitch id={id} />
                    </>
                }
                docsURL={DOCS_URL}
                customHog={HedgehogResearch}
                hogLayout="responsive"
                useMainContentContainerQueries
            />
        )
    }

    return (
        <ProductIntroduction
            thingName="suggestion"
            titleOverride="Watching this workflow"
            description="PostHog reads this workflow's metrics once a day and files a suggestion here when it finds a change worth making. Transactional emails, like receipts or support replies, are not reviewed."
            actionElementOverride={<WorkflowSuggestionsSwitch id={id} />}
            docsURL={DOCS_URL}
            customHog={HedgehogResearch}
            hogLayout="responsive"
            useMainContentContainerQueries
        />
    )
}
