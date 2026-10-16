import { IconCheck, IconMCP } from '@posthog/icons'
import { LemonButton, Spinner } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'

import type { MCPActivityRecentCallApi } from '../generated/api.schemas'
import { SetupConnectStep } from './SetupConnectStep'
import { SetupFirstCallStep } from './SetupFirstCallStep'
import { MCP_SETUP_STEPS, type MCPConnectState, type MCPSetupExitReason, type MCPSetupStep } from './setupMode'
import { SetupUsefulStep } from './SetupUsefulStep'

const COPY = {
    title: 'Set up MCP analytics',
    exit: 'Back to overview',
    steps: { connect: 'Connect', 'first-call': 'First call', useful: 'Make it useful' } satisfies Record<
        MCPSetupStep,
        string
    >,
}

export interface MCPSetupModeViewProps {
    /** `null` while the onboarding signals have not answered yet. */
    step: MCPSetupStep | null
    connectState: MCPConnectState
    recentCalls: MCPActivityRecentCallApi[] | null
    recentCallsFailed: boolean
    agentPrompt: string | null
    onExit: (reason: MCPSetupExitReason) => void
    onGoToUseful: () => void
}

function StepRail({ current }: { current: MCPSetupStep | null }): JSX.Element {
    const currentIndex = current ? MCP_SETUP_STEPS.indexOf(current) : -1
    return (
        <ol className="m-0 flex list-none flex-wrap items-center gap-x-3 gap-y-1 p-0 text-sm" aria-label="Setup steps">
            {MCP_SETUP_STEPS.map((step, index) => {
                const done = index < currentIndex
                const active = index === currentIndex
                return (
                    <li
                        key={step}
                        className={cn('flex items-center gap-1.5', active ? 'font-semibold' : 'text-secondary')}
                        aria-current={active ? 'step' : undefined}
                    >
                        <span
                            className={cn(
                                'flex size-5 shrink-0 items-center justify-center rounded-full border text-xs',
                                done && 'border-success bg-success text-white',
                                active && 'border-primary-3000 bg-primary-3000 text-white',
                                !done && !active && 'border-primary'
                            )}
                        >
                            {done ? <IconCheck /> : index + 1}
                        </span>
                        {COPY.steps[step]}
                    </li>
                )
            })}
        </ol>
    )
}

function StepBody({ step, ...props }: MCPSetupModeViewProps & { step: MCPSetupStep }): JSX.Element {
    if (step === 'connect') {
        return <SetupConnectStep connectState={props.connectState} agentPrompt={props.agentPrompt} />
    }
    if (step === 'first-call') {
        return (
            <SetupFirstCallStep
                calls={props.recentCalls}
                loadFailed={props.recentCallsFailed}
                onNext={props.onGoToUseful}
            />
        )
    }
    return <SetupUsefulStep onFinish={() => props.onExit('finished')} />
}

/** The fullscreen setup walkthrough: a header with the step rail, and the current step below it. */
export function MCPSetupModeView(props: MCPSetupModeViewProps): JSX.Element {
    const { step, onExit } = props
    return (
        <div className="@container/setup-mode flex min-h-0 w-full flex-1 flex-col bg-primary">
            <header className="flex shrink-0 flex-wrap items-center justify-between gap-x-6 gap-y-2 border-b border-primary px-4 py-3">
                <span className="flex items-center gap-2 font-semibold">
                    <IconMCP className="text-lg" />
                    {COPY.title}
                </span>
                <span className="order-last w-full @min-[48rem]/setup-mode:order-none @min-[48rem]/setup-mode:w-auto">
                    <StepRail current={step} />
                </span>
                <LemonButton
                    size="small"
                    type="secondary"
                    onClick={() => onExit('back')}
                    data-attr="mcp-analytics-setup-mode-exit"
                >
                    {COPY.exit}
                </LemonButton>
            </header>
            <div className="min-h-0 flex-1 overflow-y-auto">
                {/* The auto margins center a short step in the window and let a tall one scroll from the top. */}
                <div className="flex min-h-full flex-col px-4 py-8 @min-[56rem]/setup-mode:px-8">
                    <div className="mx-auto my-auto w-full max-w-6xl">
                        {step ? (
                            <StepBody {...props} step={step} />
                        ) : (
                            <div className="flex justify-center">
                                <Spinner className="text-2xl" />
                            </div>
                        )}
                    </div>
                </div>
            </div>
        </div>
    )
}
