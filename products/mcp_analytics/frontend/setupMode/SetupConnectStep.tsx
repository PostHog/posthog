import * as magnifyingGlassPng from '@posthog/brand/hoggies/png/magnifying-glass'
import { IconCopy, IconExternal } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { pngHoggie } from 'lib/brand/hoggies'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { StepIcon } from 'scenes/onboarding/shared/wizard-sync/StepIcon'
import { Timeline } from 'scenes/onboarding/shared/wizard-sync/Timeline'

import { SetupCallsPanel } from './SetupCallsPanel'
import type { MCPConnectState, MCPSetupPath } from './setupMode'
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
        lead: 'Follow these steps. This page moves on by itself when your server connects.',
        help: 'Need help?',
        installGuide: 'Read the install guide',
    },
    nextSteps: {
        title: 'Your next steps',
        install: {
            wizard: {
                title: "Run the Wizard command in your server's repository",
                detail: 'The setup agent installs the SDK and adds your project token.',
                alternative: 'Or run the Wizard command instead:',
                copied: 'Wizard command',
            },
            agent: {
                title: 'Paste the prompt into your coding agent',
                detail: "Open your server's repository in Claude Code, Cursor or Codex first.",
                alternative: 'Or paste this prompt into your coding agent:',
                copied: 'installation prompt',
            },
        } satisfies Record<MCPSetupPath, { title: string; detail: string; alternative: string; copied: string }>,
        restart: 'Restart your server when setup is done',
        connect: 'Your server connects',
        connectWaiting: 'This step ticks when your server sends its first event.',
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

const pendingIcon = <span className="size-4 rounded-full border-2 border-secondary" />

function CopyableLine({ text, label, dataAttr }: { text: string; label: string; dataAttr: string }): JSX.Element {
    return (
        <div className="mt-1 flex min-w-0 items-center gap-2 rounded border border-primary bg-surface-secondary py-1 pl-3 pr-1">
            <span className="min-w-0 flex-1 truncate font-mono text-xs">{text}</span>
            <LemonButton
                size="small"
                type="secondary"
                icon={<IconCopy />}
                onClick={() => void copyToClipboard(text, label)}
                data-attr={dataAttr}
            >
                Copy
            </LemonButton>
        </div>
    )
}

const OTHER_PATH: Record<MCPSetupPath, MCPSetupPath> = { wizard: 'agent', agent: 'wizard' }

/**
 * What the user does next. The first step leads with the button that opened setup mode and offers the other
 * route below it, so switching doesn't mean leaving setup mode. Only the last step is observable.
 */
function NextSteps({
    setupPath,
    installTexts,
    connected,
}: {
    setupPath: MCPSetupPath
    /** `null` once connected, when there is nothing left to copy. */
    installTexts: Record<MCPSetupPath, string | null> | null
    connected: boolean
}): JSX.Element {
    const copy = COPY.nextSteps
    const install = copy.install[setupPath]
    const otherPath = OTHER_PATH[setupPath]
    const chosenText = installTexts?.[setupPath]
    const otherText = installTexts?.[otherPath]
    const done = <StepIcon status="completed" />
    return (
        <div className="flex flex-col gap-3 rounded border border-primary bg-surface-primary p-4">
            <span className="text-xs font-semibold text-secondary">{copy.title}</span>
            <Timeline
                ariaLabel={copy.title}
                items={[
                    {
                        key: 'install',
                        icon: connected ? done : pendingIcon,
                        content: <span className="text-sm font-semibold">{install.title}</span>,
                        detail: (
                            <div className="flex flex-col gap-1">
                                <span className="block text-sm text-secondary">{install.detail}</span>
                                {chosenText ? (
                                    <CopyableLine
                                        text={chosenText}
                                        label={install.copied}
                                        dataAttr={`mcp-analytics-setup-mode-copy-${setupPath}`}
                                    />
                                ) : null}
                                {otherText ? (
                                    <>
                                        <span className="mt-2 block text-xs text-secondary">
                                            {copy.install[otherPath].alternative}
                                        </span>
                                        <CopyableLine
                                            text={otherText}
                                            label={copy.install[otherPath].copied}
                                            dataAttr={`mcp-analytics-setup-mode-copy-${otherPath}`}
                                        />
                                    </>
                                ) : null}
                            </div>
                        ),
                    },
                    {
                        key: 'restart',
                        icon: connected ? done : pendingIcon,
                        content: <span className="text-sm font-semibold">{copy.restart}</span>,
                    },
                    {
                        key: 'connect',
                        icon: <StepIcon status={connected ? 'completed' : 'in_progress'} />,
                        content: <span className="text-sm font-semibold">{copy.connect}</span>,
                        detail: connected ? undefined : (
                            <span className="block text-sm text-secondary">{copy.connectWaiting}</span>
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

function ConnectWaiting(props: SetupConnectStepProps): JSX.Element {
    return (
        <>
            <SetupStepHero Hedgehog={HedgehogSearching} title={COPY.waiting.title} lead={COPY.waiting.lead} />
            <NextSteps
                setupPath={props.setupPath}
                installTexts={{ wizard: props.wizardCommand, agent: props.agentPrompt }}
                connected={false}
            />
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

interface SetupConnectStepProps {
    connectState: MCPConnectState
    setupPath: MCPSetupPath
    agentPrompt: string | null
    wizardCommand: string | null
}

function ConnectStepBody(props: SetupConnectStepProps): JSX.Element {
    if (props.connectState.kind === 'connected') {
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
                <NextSteps setupPath={props.setupPath} installTexts={null} connected />
            </>
        )
    }
    return <ConnectWaiting {...props} />
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
