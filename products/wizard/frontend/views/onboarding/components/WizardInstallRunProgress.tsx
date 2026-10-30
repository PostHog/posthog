import { IconCheckCircle, IconClock, IconXCircle } from '@posthog/icons'
import { Spinner } from '@posthog/lemon-ui'

import type { WizardRunApi, WizardRunTaskApi } from '../../../generated/api.schemas'
import {
    WIZARD_RUN_PROGRESS_STEPS,
    WizardRunProgressStep,
    wizardRunProgressStates,
} from '../../../lib/wizardRunDisplay'
import type { WizardRunProgressState } from '../../../lib/wizardRunDisplay'

const STEP_LABELS: Record<WizardRunProgressStep, string> = {
    [WizardRunProgressStep.Starting]: 'Starting',
    [WizardRunProgressStep.PreparingWorkspace]: 'Preparing',
    [WizardRunProgressStep.ExecutingWizard]: 'Running',
    [WizardRunProgressStep.CreatingArtifacts]: 'Finishing',
}

const TASK_STATES: Record<WizardRunTaskApi['status'], WizardRunProgressState> = {
    created: 'pending',
    running: 'active',
    completed: 'complete',
    failed: 'failed',
}

function StepIcon({ state }: { state: WizardRunProgressState }): JSX.Element {
    if (state === 'active') {
        return <Spinner />
    }
    if (state === 'complete') {
        return <IconCheckCircle className="text-success" />
    }
    return state === 'failed' ? <IconXCircle className="text-danger" /> : <IconClock className="text-muted" />
}

export function WizardInstallRunProgress({
    run,
    tasks,
}: {
    run: WizardRunApi
    tasks: readonly WizardRunTaskApi[]
}): JSX.Element {
    const stepStates = wizardRunProgressStates(run)
    const visibleTasks = tasks.slice(0, 3)
    return (
        <>
            <div className="mt-3 flex flex-wrap gap-x-3 gap-y-1.5">
                {WIZARD_RUN_PROGRESS_STEPS.map((step) => (
                    <span key={step} className="flex items-center gap-1 text-2xs text-muted">
                        <StepIcon state={stepStates[step]} />
                        <span>{STEP_LABELS[step]}</span>
                    </span>
                ))}
            </div>
            {visibleTasks.length > 0 && (
                <ul className="mt-3 mb-0 list-none space-y-1 p-0">
                    {visibleTasks.map((task) => (
                        <li key={task.name} className="flex items-center gap-2 text-xs">
                            <StepIcon state={TASK_STATES[task.status]} />
                            <span className="truncate ph-no-capture">{task.name}</span>
                        </li>
                    ))}
                    {tasks.length > visibleTasks.length && (
                        <li className="pl-6 text-2xs text-muted">{`+${tasks.length - visibleTasks.length} more tasks`}</li>
                    )}
                </ul>
            )}
        </>
    )
}
