import * as magnifyingGlassPng from '@posthog/brand/hoggies/png/magnifying-glass'
import * as wizardPng from '@posthog/brand/hoggies/png/wizard-1'
import { IconCopy, IconExternal } from '@posthog/icons'
import { LemonBanner, LemonButton, Spinner } from '@posthog/lemon-ui'

import { pngHoggie } from 'lib/brand/hoggies'
import { TerminalCard } from 'lib/components/CommandBlock/TerminalCard'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { StepIcon } from 'scenes/onboarding/shared/wizard-sync/StepIcon'
import { Timeline } from 'scenes/onboarding/shared/wizard-sync/Timeline'

import { useMCPAnalyticsWizardCommand } from '../onboarding/MCPAnalyticsInstall'
import { SetupCallsPanel } from './SetupCallsPanel'
import type { MCPConnectState, MCPSetupPath, MCPWizardRun } from './setupMode'
import { SetupStepHero } from './SetupStepHero'
import { SetupStepLayout } from './SetupStepLayout'

const HedgehogWizard = pngHoggie(wizardPng)
const HedgehogSearching = pngHoggie(magnifyingGlassPng)

const INSTALL_GUIDE_URL = 'https://posthog.com/docs/mcp-analytics/installation'

// The public leaderboard is built from PostHog's own MCP server, the same data this product shows.
const LEADERBOARD_URL =
    'https://posthog.com/mcp/leaderboard?utm_medium=in-product&utm_campaign=mcp-analytics-setup-mode'

const COPY = {
    wizardWaiting: {
        title: 'Run Wizard in your terminal',
        lead: "Paste the command in your MCP server's repository. The setup agent reports its progress here as it works.",
        status: 'Waiting for the setup agent to start',
    },
    wizardRunning: {
        title: 'Wizard is setting up your server',
        lead: 'These tasks come live from your terminal. The setup agent picks them as it goes, so they change from run to run.',
        source: 'Live from your terminal',
        planning: 'The setup agent started. Waiting for its plan.',
        question: 'The setup agent has a question for you in the terminal',
        status: 'Waiting for your server to start',
    },
    agentWaiting: {
        title: 'Waiting for your server to connect',
        lead: "Your coding agent is making the change in your server's repository.",
        stuck: 'Agent stuck?',
        copyPrompt: 'Copy the prompt again',
        installGuide: 'Read the install guide',
        useWizard: 'Use Wizard instead',
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

function StatusRow({ children }: { children: string }): JSX.Element {
    return (
        <div className="flex items-center gap-2 text-sm text-secondary">
            <Spinner />
            <span>{children}</span>
        </div>
    )
}

function WizardRunProgress({ run }: { run: MCPWizardRun }): JSX.Element {
    const done = run.tasks.filter((task) => task.status === 'completed').length
    return (
        <div className="flex flex-col gap-3 rounded border border-primary bg-surface-primary p-4">
            <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-secondary">
                <span className="font-semibold">{COPY.wizardRunning.source}</span>
                {run.tasks.length > 0 ? (
                    <span translate="no">
                        {done}/{run.tasks.length} tasks
                    </span>
                ) : null}
            </div>
            {run.tasks.length > 0 ? (
                <Timeline
                    ariaLabel="Setup agent tasks"
                    items={run.tasks.map((task) => ({
                        key: task.id,
                        icon: <StepIcon status={task.status} />,
                        content: <span className="text-sm">{task.label}</span>,
                    }))}
                />
            ) : (
                <StatusRow>{COPY.wizardRunning.planning}</StatusRow>
            )}
            {run.pendingInput ? (
                <LemonBanner type="warning">
                    <div className="font-semibold">{COPY.wizardRunning.question}</div>
                    {run.pendingInput.sensitive
                        ? null
                        : run.pendingInput.prompts.map((prompt) => <div key={prompt}>{prompt}</div>)}
                </LemonBanner>
            ) : null}
            {run.error ? (
                <LemonBanner type="error">
                    <div className="font-semibold">{run.error.title}</div>
                    {run.error.detail ? <div>{run.error.detail}</div> : null}
                </LemonBanner>
            ) : null}
            <StatusRow>{COPY.wizardRunning.status}</StatusRow>
        </div>
    )
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

function WizardWaiting(): JSX.Element {
    const { command, isCloudOrDev } = useMCPAnalyticsWizardCommand()
    return (
        <>
            <SetupStepHero Hedgehog={HedgehogWizard} title={COPY.wizardWaiting.title} lead={COPY.wizardWaiting.lead} />
            {isCloudOrDev ? <TerminalCard command={command} copyLabel="MCP analytics wizard command" /> : null}
            <StatusRow>{COPY.wizardWaiting.status}</StatusRow>
        </>
    )
}

function AgentWaiting({
    agentPrompt,
    onUseWizard,
}: {
    agentPrompt: string | null
    onUseWizard: () => void
}): JSX.Element {
    return (
        <>
            <SetupStepHero Hedgehog={HedgehogSearching} title={COPY.agentWaiting.title} lead={COPY.agentWaiting.lead} />
            <AgentChecklist connected={false} />
            <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm">
                <span className="text-secondary">{COPY.agentWaiting.stuck}</span>
                <LemonButton
                    size="small"
                    type="tertiary"
                    icon={<IconCopy />}
                    disabledReason={agentPrompt ? undefined : 'Select a project to get the prompt.'}
                    onClick={() => agentPrompt && void copyToClipboard(agentPrompt, 'installation prompt')}
                    data-attr="mcp-analytics-setup-mode-copy-prompt"
                >
                    {COPY.agentWaiting.copyPrompt}
                </LemonButton>
                <LemonButton
                    size="small"
                    type="tertiary"
                    to={INSTALL_GUIDE_URL}
                    targetBlank
                    data-attr="mcp-analytics-setup-mode-install-guide"
                >
                    {COPY.agentWaiting.installGuide}
                </LemonButton>
                <LemonButton
                    size="small"
                    type="tertiary"
                    onClick={onUseWizard}
                    data-attr="mcp-analytics-setup-mode-use-wizard"
                >
                    {COPY.agentWaiting.useWizard}
                </LemonButton>
            </div>
        </>
    )
}

interface SetupConnectStepProps {
    path: MCPSetupPath
    connectState: MCPConnectState
    agentPrompt: string | null
    onUseWizard: () => void
}

function ConnectStepBody({ path, connectState, agentPrompt, onUseWizard }: SetupConnectStepProps): JSX.Element {
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
                {path === 'agent' ? <AgentChecklist connected /> : null}
            </>
        )
    }
    if (connectState.kind === 'wizard-running') {
        return (
            <>
                <SetupStepHero
                    Hedgehog={HedgehogWizard}
                    title={COPY.wizardRunning.title}
                    lead={COPY.wizardRunning.lead}
                />
                <WizardRunProgress run={connectState.run} />
            </>
        )
    }
    return path === 'wizard' ? <WizardWaiting /> : <AgentWaiting agentPrompt={agentPrompt} onUseWizard={onUseWizard} />
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
