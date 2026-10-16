import * as errorPng from '@posthog/brand/hoggies/png/error'
import * as partyPng from '@posthog/brand/hoggies/png/party'
import { IconArrowRight } from '@posthog/icons'
import { LemonBanner, LemonButton, Spinner } from '@posthog/lemon-ui'

import { pngHoggie } from 'lib/brand/hoggies'

import type { MCPActivityRecentCallApi } from '../generated/api.schemas'
import { SetupCallsPanel } from './SetupCallsPanel'
import { SetupStepHero } from './SetupStepHero'
import { SetupStepLayout } from './SetupStepLayout'
import { ToolCallHeroCard } from './ToolCallHeroCard'
import { ToolCallRevealCard } from './ToolCallRevealCard'

const HedgehogParty = pngHoggie(partyPng)
const HedgehogError = pngHoggie(errorPng)

/** The newest call as a hero card and the one before it as a smaller card. Later calls go to the panel. */
const REVEALED_CALLS = 2

const COPY = {
    loading: 'Loading your first tool call',
    failedToLoad: "Couldn't load your tool calls. This page tries again in a few seconds.",
    none: {
        title: 'No tool calls in the last 30 days',
        lead: 'Call a tool from your agent and it shows up here.',
    },
    success: {
        title: (count: number) =>
            count > 1 ? 'Your first tool calls just landed' : 'Your first tool call just landed',
        lead: 'This is what every call looks like in PostHog: which client called which tool, why, and how it went.',
        next: 'Make it useful',
    },
    failure: {
        title: (count: number, failed: number) =>
            count === 1
                ? 'Your first tool call failed'
                : failed === count
                  ? 'Both of your first tool calls failed'
                  : 'Two calls in, and one already needs you',
        lead: "PostHog caught the error your agent got back. Failures like this are the ones you'll want to hear about.",
        next: 'Catch these automatically',
    },
    live: 'New calls keep arriving here.',
}

interface SetupFirstCallStepProps {
    calls: MCPActivityRecentCallApi[] | null
    loadFailed: boolean
    onNext: () => void
}

function FirstCallBody({ calls, loadFailed, onNext }: SetupFirstCallStepProps): JSX.Element {
    if (calls === null) {
        return loadFailed ? (
            <LemonBanner type="error">{COPY.failedToLoad}</LemonBanner>
        ) : (
            <div className="flex items-center gap-2 text-secondary">
                <Spinner />
                <span>{COPY.loading}</span>
            </div>
        )
    }

    const revealed = calls.slice(0, REVEALED_CALLS)
    const failed = revealed.filter((call) => call.is_error).length
    const copy = failed > 0 ? COPY.failure : COPY.success
    const next = (
        <div className="flex justify-end">
            <LemonButton
                type="primary"
                sideIcon={<IconArrowRight />}
                onClick={onNext}
                data-attr="mcp-analytics-setup-mode-next"
            >
                {copy.next}
            </LemonButton>
        </div>
    )

    if (calls.length === 0) {
        return (
            <>
                <SetupStepHero Hedgehog={HedgehogParty} title={COPY.none.title} lead={COPY.none.lead} />
                {next}
            </>
        )
    }

    const [newest, previous] = revealed
    return (
        <>
            <SetupStepHero
                Hedgehog={failed > 0 ? HedgehogError : HedgehogParty}
                title={failed > 0 ? COPY.failure.title(revealed.length, failed) : COPY.success.title(revealed.length)}
                lead={copy.lead}
            />
            <ToolCallHeroCard call={newest} />
            {previous ? <ToolCallRevealCard call={previous} /> : null}
            {next}
        </>
    )
}

export function SetupFirstCallStep(props: SetupFirstCallStepProps): JSX.Element {
    return (
        <SetupStepLayout
            aside={
                <SetupCallsPanel
                    calls={props.calls?.slice(REVEALED_CALLS) ?? null}
                    status={{ kind: 'live', text: COPY.live }}
                    empty={null}
                />
            }
        >
            <FirstCallBody {...props} />
        </SetupStepLayout>
    )
}
