import * as asleepPng from '@posthog/brand/hoggies/png/asleep'
import * as handClaspPng from '@posthog/brand/hoggies/png/hand-clasp'
import * as magnifyingGlassPng from '@posthog/brand/hoggies/png/magnifying-glass'
import * as reporterPng from '@posthog/brand/hoggies/png/reporter'
import { IconCopy } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { pngHoggie } from 'lib/brand/hoggies'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { StepIcon } from 'scenes/onboarding/shared/wizard-sync/StepIcon'
import { Timeline } from 'scenes/onboarding/shared/wizard-sync/Timeline'

import { HedgehogTipCard } from '../components/HedgehogTipCard'
import { SetupCallsPanel } from './SetupCallsPanel'
import type { MCPConnectState } from './setupMode'
import { SetupStepHero } from './SetupStepHero'
import { SetupStepLayout } from './SetupStepLayout'

const HedgehogSearching = pngHoggie(magnifyingGlassPng)
const HedgehogHandClasp = pngHoggie(handClaspPng)
const HedgehogReporter = pngHoggie(reporterPng)
const HedgehogAsleep = pngHoggie(asleepPng)

const INSTALL_GUIDE_URL = 'https://posthog.com/docs/mcp-analytics/installation'

const COPY = {
    waiting: {
        title: 'Waiting for your server to connect',
        help: 'Need help?',
        installGuide: 'Read the install guide',
    },
    nextSteps: {
        title: 'Your next steps',
        restart: 'Restart your server when setup is done',
        connect: 'Waiting for your server to connect',
    },
    proTip: {
        title: 'Pro tip while you wait',
        body: "We ask agents what they were trying to achieve when they call your server. It's like a mini user interview to help you make better tools.",
        link: 'Learn about Agent Intent',
    },
    connected: {
        title: 'Your server is connected. Now call a tool.',
        lead: 'Ask your agent to do something that uses one of your tools. The first call shows up here within seconds.',
        prompt: 'Use one of the tools on my MCP server and tell me what it returned.',
    },
    funFact: {
        title: 'Fun fact while you wait',
        body: 'We group tasks in stateless and serverless servers in the same session for simpler debugging.',
        link: 'Learn how we identify users',
    },
    listening: 'Listening for your first tool call',
}

function NextSteps(): JSX.Element {
    const copy = COPY.nextSteps
    return (
        <div className="flex flex-col gap-3 rounded border border-primary bg-surface-primary p-4">
            <span className="text-xs font-semibold text-secondary">{copy.title}</span>
            <Timeline
                ariaLabel={copy.title}
                items={[
                    {
                        key: 'restart',
                        icon: <span className="size-4 rounded-full border-2 border-secondary" />,
                        content: <span className="text-sm font-semibold">{copy.restart}</span>,
                    },
                    {
                        key: 'connect',
                        icon: <StepIcon status="in_progress" />,
                        content: <span className="text-sm font-semibold">{copy.connect}</span>,
                    },
                ]}
            />
        </div>
    )
}

function ConnectWaiting(): JSX.Element {
    return (
        <>
            <SetupStepHero Hedgehog={HedgehogSearching} title={COPY.waiting.title} />
            <NextSteps />
            <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm">
                <span className="text-secondary">{COPY.waiting.help}</span>
                <LemonButton
                    size="small"
                    type="tertiary"
                    to={INSTALL_GUIDE_URL}
                    targetBlank
                    data-attr="mcp-analytics-setup-mode-install-guide"
                >
                    {COPY.waiting.installGuide}
                </LemonButton>
            </div>
        </>
    )
}

function ConnectConnected(): JSX.Element {
    return (
        <>
            <SetupStepHero Hedgehog={HedgehogHandClasp} title={COPY.connected.title} lead={COPY.connected.lead} />
            <div className="flex flex-wrap items-center gap-2 rounded border border-primary bg-surface-primary p-3">
                <span className="min-w-0 flex-1 font-mono text-xs">{COPY.connected.prompt}</span>
                <LemonButton
                    size="small"
                    type="secondary"
                    icon={<IconCopy />}
                    onClick={() => void copyToClipboard(COPY.connected.prompt, 'prompt')}
                    data-attr="mcp-analytics-setup-mode-copy-try-prompt"
                >
                    Copy
                </LemonButton>
            </div>
        </>
    )
}

export function SetupConnectStep({ connectState }: { connectState: MCPConnectState }): JSX.Element {
    const connected = connectState.kind === 'connected'
    return (
        <SetupStepLayout
            aside={
                <>
                    <SetupCallsPanel calls="example" status={{ kind: 'listening', text: COPY.listening }} />
                    {connected ? (
                        <HedgehogTipCard
                            Hedgehog={HedgehogAsleep}
                            title={COPY.funFact.title}
                            body={COPY.funFact.body}
                            link={{
                                label: COPY.funFact.link,
                                to: 'https://posthog.com/docs/mcp-analytics/identifying-users',
                                dataAttr: 'mcp-analytics-setup-mode-identify-users',
                            }}
                        />
                    ) : (
                        <HedgehogTipCard
                            Hedgehog={HedgehogReporter}
                            title={COPY.proTip.title}
                            body={COPY.proTip.body}
                            link={{
                                label: COPY.proTip.link,
                                to: 'https://posthog.com/docs/mcp-analytics/intent',
                                dataAttr: 'mcp-analytics-setup-mode-agent-intent',
                            }}
                        />
                    )}
                </>
            }
        >
            {connected ? <ConnectConnected /> : <ConnectWaiting />}
        </SetupStepLayout>
    )
}
