import * as magnifyingGlassPng from '@posthog/brand/hoggies/png/magnifying-glass'
import * as wizardPng from '@posthog/brand/hoggies/png/wizard-1'
import { IconCopy } from '@posthog/icons'
import { LemonBanner, LemonButton, Spinner } from '@posthog/lemon-ui'

import { pngHoggie } from 'lib/brand/hoggies'
import { TerminalCard } from 'lib/components/CommandBlock/TerminalCard'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { StepIcon } from 'scenes/onboarding/shared/wizard-sync/StepIcon'
import { Timeline } from 'scenes/onboarding/shared/wizard-sync/Timeline'

import { useMCPAnalyticsWizardCommand } from '../onboarding/MCPAnalyticsInstall'
import type { MCPConnectState, MCPSetupPath, MCPWizardRun } from './setupMode'
import { SetupStepHero } from './SetupStepHero'

const HedgehogWizard = pngHoggie(wizardPng)
const HedgehogSearching = pngHoggie(magnifyingGlassPng)

const INSTALL_GUIDE_URL = 'https://posthog.com/docs/mcp-analytics/installation'

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
        lead: "Your coding agent is making the change. This page can't see its progress, so it waits for your server to send its first event.",
        status: 'Listening for your server',
        statusDetail: 'It shows up here once it starts with the SDK installed. Restart it after your agent is done.',
        stuck: 'Agent stuck?',
        copyPrompt: 'Copy the prompt again',
        installGuide: 'Read the install guide',
        useWizard: 'Use Wizard instead',
    },
    connected: {
        title: 'Your server is connected. Now call a tool',
        lead: 'Ask your agent to do something that uses one of your tools. The first call shows up here within seconds.',
        prompt: 'Use one of the tools on my MCP server and tell me what it returned.',
        status: 'Listening for your first tool call',
    },
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
            <div className="flex items-start gap-3 rounded border border-primary bg-surface-primary p-4">
                <Spinner className="mt-0.5 shrink-0" />
                <div className="flex min-w-0 flex-col gap-0.5 text-sm">
                    <span className="font-semibold">{COPY.agentWaiting.status}</span>
                    <span className="text-secondary">{COPY.agentWaiting.statusDetail}</span>
                </div>
            </div>
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

export function SetupConnectStep({
    path,
    connectState,
    agentPrompt,
    onUseWizard,
}: {
    path: MCPSetupPath
    connectState: MCPConnectState
    agentPrompt: string | null
    onUseWizard: () => void
}): JSX.Element {
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
                <StatusRow>{COPY.connected.status}</StatusRow>
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
