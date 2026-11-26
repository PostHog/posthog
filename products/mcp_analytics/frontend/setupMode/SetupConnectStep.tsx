import type { ReactNode } from 'react'

import * as handClaspPng from '@posthog/brand/hoggies/png/hand-clasp'
import * as magnifyingGlassPng from '@posthog/brand/hoggies/png/magnifying-glass'
import { IconCopy } from '@posthog/icons'
import { LemonButton, Spinner } from '@posthog/lemon-ui'

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
        title: 'Connect your server to PostHog',
        steps: {
            install: { title: 'Add MCP analytics to your server' },
            restart: { title: 'Restart your server', detail: 'Redeploy it if it runs remotely.' },
            connect: {
                title: 'Connect your agent and call a tool',
                detail: 'Claude, Cursor, or any other MCP client works. Ask it for anything that uses one of your tools. This page moves on by itself.',
            },
        },
        cue: 'Waiting for a connection or a tool call',
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
        lead: 'Paste this prompt into the agent connected to your server, or ask it for anything that uses one of your tools.',
        prompt: 'Use one of the tools on my MCP server and tell me what it returned.',
        cue: 'Waiting for your first tool call. It shows up here within seconds.',
    },
    funFact: {
        title: 'Fun fact while you wait',
        body: 'We group tasks in stateless and serverless servers in the same session for simpler debugging.',
        link: 'Learn how we identify users',
    },
}

function ConnectTask({
    title,
    detail,
    children,
}: {
    title: string
    detail?: string
    children?: ReactNode
}): JSX.Element {
    return (
        <li className="marker:font-semibold">
            <div className="flex flex-col gap-2">
                <span className="font-semibold">{title}</span>
                {detail ? <span className="text-secondary">{detail}</span> : null}
                {children}
            </div>
        </li>
    )
}

function WaitingCue({ label }: { label: string }): JSX.Element {
    return (
        <div className="flex items-center gap-2 text-sm text-secondary">
            <Spinner />
            <span>{label}</span>
        </div>
    )
}

function ConnectWaiting(): JSX.Element {
    const { steps } = COPY.waiting
    return (
        <>
            <SetupStepHero Hedgehog={HedgehogSearching} title={COPY.waiting.title} />
            <ol className="m-0 flex list-decimal flex-col gap-4 pl-5 text-sm">
                <ConnectTask title={steps.install.title}>
                    <SetupInstallOptions />
                </ConnectTask>
                <ConnectTask {...steps.restart} />
                <ConnectTask {...steps.connect} />
            </ol>
            <WaitingCue label={COPY.waiting.cue} />
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
            <WaitingCue label={COPY.connected.cue} />
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
