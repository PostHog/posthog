import { IconCheckCircle, IconClock, IconWarning, IconXCircle } from '@posthog/icons'
import { Spinner } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'

import type { WizardRunApi } from '../generated/api.schemas'
import { wizardRunFailureStage, wizardWorkspaceLabel } from '../wizardRunDisplay'
import { wizardRunErrorDetails } from './wizardRunErrorCatalog'

type ProgressState = 'complete' | 'active' | 'pending' | 'failed'

function stagePosition(run: WizardRunApi): number {
    if (run.status === 'completed') {
        return 4
    }
    if (run.status === 'created') {
        return 0
    }

    const stage = run.status === 'failed' ? wizardRunFailureStage(run) : run.stage

    switch (stage) {
        case 'dispatching':
        case 'provisioning':
            return 0
        case 'preparing_workspace':
            return 1
        case 'executing_wizard':
            return 2
        case 'creating_artifacts':
            return 3
        default:
            return run.status === 'running' ? 2 : 0
    }
}

function progressState(run: WizardRunApi, step: number): ProgressState {
    const position = stagePosition(run)

    if (run.status === 'failed' && position === step) {
        return 'failed'
    }
    if (run.status === 'cancelled' && position === step) {
        return 'failed'
    }
    if (position > step) {
        return 'complete'
    }
    if (position === step && run.status !== 'completed') {
        return 'active'
    }
    return 'pending'
}

function ProgressIcon({ state }: { state: ProgressState }): JSX.Element {
    if (state === 'complete') {
        return <IconCheckCircle className="text-success" />
    }
    if (state === 'active') {
        return <Spinner textColored />
    }
    if (state === 'failed') {
        return <IconXCircle className="text-danger" />
    }
    return <IconClock className="text-muted" />
}

export function WizardRunProgress({ run }: { run: WizardRunApi }): JSX.Element {
    const runError = wizardRunErrorDetails(run.error_code, run.error_message)
    const position = stagePosition(run)
    const steps = [
        {
            title: 'Run created',
            detail: run.created_at ? <TZLabel time={run.created_at} /> : 'Waiting to start',
        },
        {
            title: 'Preparing workspace',
            detail:
                run.workspace.type === 'git_repository'
                    ? `Repository: ${run.workspace.repository}`
                    : `Folder: ${wizardWorkspaceLabel(run)}`,
        },
        {
            title: 'Running Wizard',
            detail: `Program: ${run.program.name}`,
        },
        {
            title: 'Finishing up',
            detail:
                run.status === 'completed'
                    ? 'Changes and artifacts are ready'
                    : position === 3
                      ? 'Saving changes and artifacts'
                      : 'Starts after the program finishes',
        },
    ]

    return (
        <div className="space-y-0">
            {steps.map((step, index) => {
                const state = progressState(run, index)
                return (
                    <div key={step.title} className="relative flex gap-3 pb-5 last:pb-0">
                        {index < steps.length - 1 && (
                            <div className="absolute left-[7px] top-5 h-[calc(100%-12px)] border-l border-primary" />
                        )}
                        <div className="relative z-10 mt-0.5 flex size-4 shrink-0 items-center justify-center bg-surface-primary">
                            <ProgressIcon state={state} />
                        </div>
                        <div className="min-w-0">
                            <div className="font-semibold">{step.title}</div>
                            <div className="text-xs text-muted">{step.detail}</div>
                            {state === 'failed' && (
                                <div className="mt-1 flex items-center gap-1 text-xs text-danger">
                                    <IconWarning /> {runError.title}
                                </div>
                            )}
                        </div>
                    </div>
                )
            })}
        </div>
    )
}
