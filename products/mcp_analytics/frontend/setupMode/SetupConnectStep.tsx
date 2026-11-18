import * as handClaspPng from '@posthog/brand/hoggies/png/hand-clasp'
import * as magnifyingGlassPng from '@posthog/brand/hoggies/png/magnifying-glass'
import { IconCopy } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { pngHoggie } from 'lib/brand/hoggies'
import { copyToClipboard } from 'lib/utils/copyToClipboard'

import { TipCard } from '../components/TipCard'
import { SetupInstallOptions } from './SetupInstallOptions'
import type { MCPConnectState, MCPServerTools } from './setupMode'
import { SetupStepHero } from './SetupStepHero'
import { SetupStepLayout } from './SetupStepLayout'
import { SetupToolsPanel } from './SetupToolsPanel'
import { SetupTroubleshootingCard } from './SetupTroubleshootingCard'

const HedgehogSearching = pngHoggie(magnifyingGlassPng)
const HedgehogHandClasp = pngHoggie(handClaspPng)

const INSTALL_GUIDE_URL = 'https://posthog.com/docs/mcp-analytics/installation'

const COPY = {
    waiting: {
        title: 'Waiting for your server to connect',
        help: 'Need help?',
        installGuide: 'Read the install guide',
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
}

function ConnectWaiting(): JSX.Element {
    return (
        <>
            <SetupStepHero Hedgehog={HedgehogSearching} title={COPY.waiting.title} />
            <SetupInstallOptions />
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

export function SetupConnectStep({
    connectState,
    serverTools,
    serverToolsFailed,
}: {
    connectState: MCPConnectState
    serverTools: MCPServerTools | null
    serverToolsFailed: boolean
}): JSX.Element {
    const connected = connectState.kind === 'connected'
    return (
        <SetupStepLayout
            aside={
                <>
                    {connected ? (
                        <SetupToolsPanel tools={serverTools} failed={serverToolsFailed} />
                    ) : (
                        <SetupTroubleshootingCard />
                    )}
                    {connected ? (
                        <TipCard
                            title={COPY.funFact.title}
                            body={COPY.funFact.body}
                            link={{
                                label: COPY.funFact.link,
                                to: 'https://posthog.com/docs/mcp-analytics/identifying-users',
                                dataAttr: 'mcp-analytics-setup-mode-identify-users',
                            }}
                        />
                    ) : (
                        <TipCard
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
