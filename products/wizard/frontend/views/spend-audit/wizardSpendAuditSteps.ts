import type { WizardRunApi, WizardRunTaskApi } from '../../generated/api.schemas'
import { WizardRunProgressStep, wizardRunProgressStep } from '../../lib/wizardRunDisplay'
import type { WizardRunProgressState } from '../../lib/wizardRunDisplay'

export type WizardSpendAuditStepKey = 'audit' | 'audit_notebook' | 'pull_requests' | 'unused_events'

export interface WizardSpendAuditStep {
    key: WizardSpendAuditStepKey
    label: string
    // Words the program's task names carry for this step, matched case-insensitively. The program
    // reports one task per piece of work, so a step with several tasks (one per audit area)
    // completes when all of them do. The spend-audit flow in context-mill labels its tasks against
    // this table; a label that drifts lands on the wrong step or on none.
    taskWords: readonly string[]
}

export const WIZARD_SPEND_AUDIT_STEPS: readonly WizardSpendAuditStep[] = [
    { key: 'audit', label: 'Audit the PostHog setup', taskWords: ['audit'] },
    { key: 'audit_notebook', label: 'Write the audit notebook', taskWords: ['notebook', 'report'] },
    // The backend opens one pull request per run, from the whole diff, after the agent exits.
    { key: 'pull_requests', label: 'Open a pull request', taskWords: ['pull request'] },
    { key: 'unused_events', label: 'Create dashboards and insights for unused events', taskWords: ['unused event'] },
]

// Most specific first, so "unused events dashboard" lands on the unused events step and
// "audit notebook" on the notebook step rather than the audit step. A pull request that
// mentions unused flags still lands on the pull requests step, because only "unused event" matches.
const MATCH_ORDER: readonly WizardSpendAuditStepKey[] = ['unused_events', 'pull_requests', 'audit_notebook', 'audit']

const TASK_STATES: Record<WizardRunTaskApi['status'], WizardRunProgressState> = {
    created: 'pending',
    running: 'active',
    completed: 'complete',
    failed: 'failed',
}

export function wizardSpendAuditStepForTask(taskName: string): WizardSpendAuditStep | null {
    const name = taskName.toLowerCase()
    for (const key of MATCH_ORDER) {
        const step = WIZARD_SPEND_AUDIT_STEPS.find((candidate) => candidate.key === key)
        if (step?.taskWords.some((word) => name.includes(word))) {
            return step
        }
    }
    return null
}

function combineTaskStates(states: readonly WizardRunProgressState[]): WizardRunProgressState {
    if (states.includes('failed')) {
        return 'failed'
    }
    if (states.includes('active')) {
        return 'active'
    }
    return states.every((state) => state === 'complete') ? 'complete' : 'pending'
}

export function wizardSpendAuditStepStates(
    run: WizardRunApi,
    tasks: readonly WizardRunTaskApi[]
): Record<WizardSpendAuditStepKey, WizardRunProgressState> {
    const states = Object.fromEntries(WIZARD_SPEND_AUDIT_STEPS.map((step) => [step.key, 'pending'])) as Record<
        WizardSpendAuditStepKey,
        WizardRunProgressState
    >
    if (run.status === 'completed') {
        for (const step of WIZARD_SPEND_AUDIT_STEPS) {
            states[step.key] = 'complete'
        }
        return states
    }

    const taskStatesByStep = new Map<WizardSpendAuditStepKey, WizardRunProgressState[]>()
    for (const task of tasks) {
        const step = wizardSpendAuditStepForTask(task.name)
        if (step) {
            taskStatesByStep.set(step.key, [...(taskStatesByStep.get(step.key) ?? []), TASK_STATES[task.status]])
        }
    }
    for (const [key, taskStates] of taskStatesByStep) {
        states[key] = combineTaskStates(taskStates)
    }

    // Until the agent reports a task, the only signal is the run stage: the audit is under way once
    // the sandbox executes the program.
    if (taskStatesByStep.size === 0 && wizardRunProgressStep(run) === WizardRunProgressStep.ExecutingWizard) {
        states.audit = run.status === 'failed' ? 'failed' : 'active'
    }

    if (run.status === 'failed' && !Object.values(states).includes('failed')) {
        const firstOpen = WIZARD_SPEND_AUDIT_STEPS.find((step) => states[step.key] !== 'complete')
        if (firstOpen) {
            states[firstOpen.key] = 'failed'
        }
    }
    return states
}
