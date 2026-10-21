import { IconCheckCircle, IconClock, IconWarning, IconXCircle } from '@posthog/icons'
import { Spinner } from '@posthog/quill-primitives'

import { TZLabel } from 'lib/components/TZLabel'

import type { WizardRunApi, WizardRunTaskApi } from '../generated/api.schemas'
import type { WizardRunProgressState } from '../wizardRunDisplay'
import {
    wizardRunFailureStage,
    wizardRunProgressState,
    wizardRunStagePosition,
    wizardWorkspaceLabel,
} from '../wizardRunDisplay'
import { wizardRunErrorDetails } from './wizardRunErrorCatalog'

function ProgressIcon({ state }: { state: WizardRunProgressState }): JSX.Element {
    if (state === 'complete') {
        return <IconCheckCircle className="text-success" />
    }
    if (state === 'active') {
        return <Spinner />
    }
    if (state === 'failed') {
        return <IconXCircle className="text-danger" />
    }
    return <IconClock className="text-muted" />
}

function RunLevelOutcome({ run }: { run: WizardRunApi }): JSX.Element | null {
    if (run.status === 'cancelled') {
        return (
            <div className="flex items-center gap-1 text-xs text-muted">
                <IconXCircle className="shrink-0" /> Run canceled
                {run.finished_at && (
                    <>
                        {' '}
                        <TZLabel time={run.finished_at} />
                    </>
                )}
                .
            </div>
        )
    }

    if (run.status !== 'failed') {
        return null
    }

    const runError = wizardRunErrorDetails(run.error_code, run.error_message)

    return (
        <div className="space-y-1 text-xs">
            <div className="flex items-center gap-1 text-danger">
                <IconXCircle className="shrink-0" /> {runError.title}
            </div>
            {runError.description !== runError.title && <div className="text-muted">{runError.description}</div>}
            {runError.resolution && (
                <div className="flex items-start gap-1 text-muted">
                    <IconWarning className="mt-0.5 shrink-0" /> {runError.resolution}
                </div>
            )}
        </div>
    )
}

export function WizardRunProgress({
    run,
    tasks = [],
}: {
    run: WizardRunApi
    tasks?: readonly WizardRunTaskApi[]
}): JSX.Element {
    const runError = wizardRunErrorDetails(run.error_code, run.error_message)
    const failedAtStep = run.status === 'failed' && wizardRunFailureStage(run)
    const steps = [
        {
            title: 'Starting run',
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
                    : wizardRunStagePosition(run) === 3
                      ? 'Saving changes and artifacts'
                      : 'Starts after the program finishes',
        },
    ]

    return (
        <div className="space-y-0">
            {steps.map((step, index) => {
                const state = wizardRunProgressState(run, index)
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
                            {index === 2 && run.status === 'running' && tasks.length > 0 && (
                                <ul className="mt-2 space-y-1 text-xs">
                                    {tasks.map((task) => (
                                        <li key={task.name} className="flex items-center gap-2">
                                            <ProgressIcon
                                                state={
                                                    task.status === 'completed'
                                                        ? 'complete'
                                                        : task.status === 'running'
                                                          ? 'active'
                                                          : task.status === 'failed'
                                                            ? 'failed'
                                                            : 'pending'
                                                }
                                            />
                                            <span className="break-words">{task.name}</span>
                                            <span className="sr-only">({task.status})</span>
                                        </li>
                                    ))}
                                </ul>
                            )}
                            {state === 'failed' && (
                                <div className="mt-1 space-y-1 text-xs">
                                    <div className="flex items-center gap-1 text-danger">
                                        <IconWarning /> {runError.title}
                                    </div>
                                    {runError.description !== runError.title && (
                                        <div className="text-muted">{runError.description}</div>
                                    )}
                                    {runError.resolution && (
                                        <div className="text-muted">Next step: {runError.resolution}</div>
                                    )}
                                </div>
                            )}
                        </div>
                    </div>
                )
            })}
            {(run.status === 'cancelled' || (run.status === 'failed' && !failedAtStep)) && (
                <div className="border-t border-primary pt-3">
                    <RunLevelOutcome run={run} />
                </div>
            )}
        </div>
    )
}
