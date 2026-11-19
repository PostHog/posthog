import * as errorPng from '@posthog/brand/hoggies/png/error'
import * as magnifyingGlassPng from '@posthog/brand/hoggies/png/magnifying-glass'
import * as partyPng from '@posthog/brand/hoggies/png/party'
import { IconArrowRight } from '@posthog/icons'
import { LemonBanner, LemonButton, Spinner } from '@posthog/lemon-ui'

import { pngHoggie } from 'lib/brand/hoggies'

import type { MCPActivityRecentCallApi } from '../generated/api.schemas'
import type { MCPServerTools } from './setupMode'
import { SetupStepHero } from './SetupStepHero'
import { SetupStepLayout } from './SetupStepLayout'
import { SetupToolsPanel } from './SetupToolsPanel'
import { ToolCallHeroCard } from './ToolCallHeroCard'
import { ToolCallRevealCard } from './ToolCallRevealCard'

const HedgehogParty = pngHoggie(partyPng)
const HedgehogError = pngHoggie(errorPng)
const HedgehogSearching = pngHoggie(magnifyingGlassPng)

/** The newest call as a hero card and the one before it as a smaller card. */
const REVEALED_CALLS = 2

const COPY = {
    loading: 'Loading your first tool call',
    failedToLoad: "Couldn't load your tool calls. This page tries again in a few seconds.",
    none: {
        title: 'No tool calls in the last 30 days',
        lead: 'Call a tool from your agent and it shows up here.',
    },
    success: {
        title: (count: number, latest: boolean) =>
            latest
                ? count > 1
                    ? 'Your latest tool calls'
                    : 'Your latest tool call'
                : count > 1
                  ? 'Your first tool calls just landed'
                  : 'Your first tool call just landed',
        lead: 'This is what every call looks like in PostHog: which client called which tool, why, and how it went.',
        next: 'Make it useful',
    },
    failure: {
        title: (count: number, failed: number, latest: boolean) =>
            count === 1
                ? `Your ${latest ? 'latest' : 'first'} tool call failed`
                : failed === count
                  ? `Both of your ${latest ? 'latest' : 'first'} tool calls failed`
                  : latest
                    ? 'One of your latest tool calls failed'
                    : 'Two calls in, and one already needs you',
        lead: "PostHog caught the error your agent got back. Failures like this are the ones you'll want to hear about.",
        next: 'Catch these automatically',
    },
}

interface SetupFirstCallStepProps {
    calls: MCPActivityRecentCallApi[] | null
    /** Every call the project has had, so a returning project's calls are not called its first. */
    toolCallsTotal: number
    loadFailed: boolean
    serverTools: MCPServerTools | null
    serverToolsFailed: boolean
    onNext: () => void
}

function FirstCallBody({
    calls,
    toolCallsTotal,
    loadFailed,
    onNext,
}: Pick<SetupFirstCallStepProps, 'calls' | 'toolCallsTotal' | 'loadFailed' | 'onNext'>): JSX.Element {
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
                <SetupStepHero Hedgehog={HedgehogSearching} title={COPY.none.title} lead={COPY.none.lead} />
                {next}
            </>
        )
    }

    const [newest, previous] = revealed
    const latest = toolCallsTotal > revealed.length
    return (
        <>
            <SetupStepHero
                Hedgehog={failed > 0 ? HedgehogError : HedgehogParty}
                title={
                    failed > 0
                        ? COPY.failure.title(revealed.length, failed, latest)
                        : COPY.success.title(revealed.length, latest)
                }
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
        <SetupStepLayout aside={<SetupToolsPanel tools={props.serverTools} failed={props.serverToolsFailed} />}>
            <FirstCallBody {...props} />
        </SetupStepLayout>
    )
}
