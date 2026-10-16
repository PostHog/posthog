import * as magnifyingGlassPng from '@posthog/brand/hoggies/png/magnifying-glass'
import { IconCopy, IconExternal } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { pngHoggie } from 'lib/brand/hoggies'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { StepIcon } from 'scenes/onboarding/shared/wizard-sync/StepIcon'
import { Timeline } from 'scenes/onboarding/shared/wizard-sync/Timeline'

import { SetupCallsPanel } from './SetupCallsPanel'
import type { MCPConnectState } from './setupMode'
import { SetupStepHero } from './SetupStepHero'
import { SetupStepLayout } from './SetupStepLayout'

const HedgehogSearching = pngHoggie(magnifyingGlassPng)

const INSTALL_GUIDE_URL = 'https://posthog.com/docs/mcp-analytics/installation'

// The public leaderboard is built from PostHog's own MCP server, the same data this product shows.
const LEADERBOARD_URL =
    'https://posthog.com/mcp/leaderboard?utm_medium=in-product&utm_campaign=mcp-analytics-setup-mode'

const COPY = {
    waiting: {
        title: 'Waiting for your server to connect',
        lead: "Setup is making the change in your server's repository.",
        stuck: 'Agent stuck?',
        copyPrompt: 'Copy the prompt again',
        installGuide: 'Read the install guide',
    },
    agentChecklist: {
        title: 'What your agent should do',
        source: "This page can't see your agent. Only the last step is live.",
        steps: ["Find your server's entry point", 'Install the PostHog MCP SDK', 'Add your project token'],
        restart: 'Restart your server',
        restartWaiting: 'Restart it after your agent is done. This step ticks when your server sends its first event.',
        restartDone: 'Your server connected.',
    },
    whileYouWait: {
        title: 'While you wait',
        lead: 'Once calls arrive, you can see:',
        items: [
            'What the agent was trying to do, for every call',
            'Failed calls, with what your server sent back',
            'Which clients and models call your tools',
        ],
        leaderboard: "See how agents use PostHog's own MCP server",
    },
    connected: {
        title: 'Your server is connected. Now call a tool',
        lead: 'Ask your agent to do something that uses one of your tools. The first call shows up here within seconds.',
        prompt: 'Use one of the tools on my MCP server and tell me what it returned.',
    },
    listening: 'Listening for your first tool call',
}

// Only the restart is observable: the server connecting proves it, and with it every step before it.
function AgentChecklist({ connected }: { connected: boolean }): JSX.Element {
    const copy = COPY.agentChecklist
    const expected = connected ? (
        <StepIcon status="completed" />
    ) : (
        <span className="size-4 rounded-full border-2 border-secondary" />
    )
    return (
        <div className="flex flex-col gap-3 rounded border border-primary bg-surface-primary p-4">
            <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-secondary">
                <span className="font-semibold">{copy.title}</span>
                {connected ? null : <span>{copy.source}</span>}
            </div>
            <Timeline
                ariaLabel={copy.title}
                items={[
                    ...copy.steps.map((label) => ({
                        key: label,
                        icon: expected,
                        content: <span className="text-sm text-secondary">{label}</span>,
                    })),
                    {
                        key: 'restart',
                        icon: <StepIcon status={connected ? 'completed' : 'in_progress'} />,
                        content: <span className="text-sm font-semibold">{copy.restart}</span>,
                        detail: (
                            <span className="block text-sm text-secondary">
                                {connected ? copy.restartDone : copy.restartWaiting}
                            </span>
                        ),
                    },
                ]}
            />
        </div>
    )
}

function WhileYouWait(): JSX.Element {
    const copy = COPY.whileYouWait
    return (
        <div className="flex flex-col gap-3 rounded border border-primary bg-surface-primary p-4">
            <div className="flex flex-col gap-1">
                <span className="font-semibold">{copy.title}</span>
                <span className="text-sm text-secondary">{copy.lead}</span>
            </div>
            <ul className="m-0 flex list-disc flex-col gap-1 pl-5 text-sm">
                {copy.items.map((item) => (
                    <li key={item}>{item}</li>
                ))}
            </ul>
            <div>
                <LemonButton
                    size="small"
                    type="secondary"
                    to={LEADERBOARD_URL}
                    targetBlank
                    sideIcon={<IconExternal />}
                    data-attr="mcp-analytics-setup-mode-leaderboard"
                >
                    {copy.leaderboard}
                </LemonButton>
            </div>
        </div>
    )
}

function ConnectWaiting({ agentPrompt }: { agentPrompt: string | null }): JSX.Element {
    return (
        <>
            <SetupStepHero Hedgehog={HedgehogSearching} title={COPY.waiting.title} lead={COPY.waiting.lead} />
            <AgentChecklist connected={false} />
            <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm">
                <span className="text-secondary">{COPY.waiting.stuck}</span>
                <LemonButton
                    size="small"
                    type="tertiary"
                    icon={<IconCopy />}
                    disabledReason={agentPrompt ? undefined : 'Select a project to get the prompt.'}
                    onClick={() => agentPrompt && void copyToClipboard(agentPrompt, 'installation prompt')}
                    data-attr="mcp-analytics-setup-mode-copy-prompt"
                >
                    {COPY.waiting.copyPrompt}
                </LemonButton>
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

interface SetupConnectStepProps {
    connectState: MCPConnectState
    agentPrompt: string | null
}

function ConnectStepBody({ connectState, agentPrompt }: SetupConnectStepProps): JSX.Element {
    if (connectState.kind === 'connected') {
        return (
            <>
                <SetupStepHero Hedgehog={HedgehogSearching} title={COPY.connected.title} lead={COPY.connected.lead} />
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
                <AgentChecklist connected />
            </>
        )
    }
    return <ConnectWaiting agentPrompt={agentPrompt} />
}

export function SetupConnectStep(props: SetupConnectStepProps): JSX.Element {
    return (
        <SetupStepLayout
            aside={
                <>
                    <SetupCallsPanel calls="example" status={{ kind: 'listening', text: COPY.listening }} />
                    <WhileYouWait />
                </>
            }
        >
            <ConnectStepBody {...props} />
        </SetupStepLayout>
    )
}
