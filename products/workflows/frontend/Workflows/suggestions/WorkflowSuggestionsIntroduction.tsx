import * as research from '@posthog/brand/hoggies/png/research'
import * as stampApproved from '@posthog/brand/hoggies/png/stamp-approved'
import { LemonButton } from '@posthog/lemon-ui'

import { pngHoggie } from 'lib/brand/hoggies'
import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { dayjs } from 'lib/dayjs'
import { urls } from 'scenes/urls'

import type { SuggestionsSampleApi, SuggestionsScoutStatusEnumApi } from '../../generated/api.schemas'
import { WorkflowSuggestionsSwitch } from './WorkflowSuggestionsSwitch'

const HedgehogStampApproved = pngHoggie(stampApproved)
const HedgehogResearch = pngHoggie(research)

const DOCS_URL = 'https://posthog.com/docs/workflows/suggestions'
const MIN_VERSION_AGE_HOURS = 48

function sampleProgress(sample: SuggestionsSampleApi | null | undefined): string | null {
    if (!sample || sample.reached) {
        return null
    }
    const sends = `${sample.tracked_sends} tracked ${sample.tracked_sends === 1 ? 'send' : 'sends'}`
    const needs = `PostHog needs ${sample.required_sends} tracked sends on one email step within 7 days, from a version that has been live for at least 2 days.`
    const liveSince = dayjs(sample.version_live_since)
    const tooNew = dayjs().diff(liveSince, 'hour') < MIN_VERSION_AGE_HOURS
    if (sample.tracked_sends >= sample.required_sends) {
        return `This version went live ${liveSince.fromNow()}. PostHog waits until a version has been live for 2 days before it judges it.`
    }
    if (tooNew) {
        return `This version went live ${liveSince.fromNow()}, and its busiest email step has had ${sends} in the last 7 days. ${needs}`
    }
    return `This version's busiest email step has had ${sends} in the last 7 days. ${needs}`
}

export function WorkflowSuggestionsIntroduction({
    id,
    enabled,
    scoutStatus,
    sample,
}: {
    id: string
    enabled: boolean
    scoutStatus?: SuggestionsScoutStatusEnumApi
    sample?: SuggestionsSampleApi | null
}): JSX.Element {
    const progress = sampleProgress(sample)
    if (!enabled) {
        return (
            <ProductIntroduction
                thingName="suggestion"
                titleOverride="Let PostHog suggest improvements"
                description={[
                    'PostHog reads how this workflow performs, such as how many people open and click each email, and suggests one concrete change when a step underperforms. Nothing reaches anyone until you approve a suggestion and publish it.',
                    progress &&
                        `PostHog can't judge this workflow yet. ${progress} You can turn suggestions on now, and they start once it can.`,
                ]
                    .filter(Boolean)
                    .join(' ')}
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
            description={[
                "PostHog reads this workflow's metrics once a day and files a suggestion here when it finds a change worth making. It waits for a version to collect a couple of days of opens before judging it, so a fresh publish takes a few days to read. Transactional emails, like receipts or support replies, are not reviewed.",
                progress,
            ]
                .filter(Boolean)
                .join(' ')}
            actionElementOverride={<WorkflowSuggestionsSwitch id={id} />}
            docsURL={DOCS_URL}
            customHog={HedgehogResearch}
            hogLayout="responsive"
            useMainContentContainerQueries
        />
    )
}
