import { IconCheck, IconMinus, IconX } from '@posthog/icons'
import { Spinner } from '@posthog/lemon-ui'

import type { AEOSetupJobApi, AEOSetupStepApi } from 'products/web_analytics/frontend/generated/api.schemas'

const STEP_LABELS: Record<AEOSetupStepApi['step'], string> = {
    brand: 'Add your site as your brand',
    prompts: 'Suggest and save prompts',
    keywords: 'Suggest and save keywords',
    first_run: 'Queue the first checks',
}

const SKIP_LABELS: Record<string, string> = {
    already_set: 'Already set up',
    already_run: 'Checks already ran',
    not_requested: 'Runs with the daily schedule',
    not_available: 'Not available for this project yet',
}

const stepNote = (step: AEOSetupStepApi): string => {
    switch (step.status) {
        case 'done':
            return step.step === 'prompts' || step.step === 'keywords' ? `Added ${step.added ?? 0}` : 'Done'
        case 'skipped':
            return SKIP_LABELS[step.detail ?? ''] ?? 'Skipped'
        case 'failed':
            return step.detail || 'Failed'
        case 'running':
            return 'Working…'
        default:
            return 'Waiting'
    }
}

const StepIcon = ({ status }: { status: AEOSetupStepApi['status'] }): JSX.Element => {
    switch (status) {
        case 'done':
            return <IconCheck className="text-success" />
        case 'failed':
            return <IconX className="text-danger" />
        case 'running':
            return <Spinner className="text-base" />
        case 'skipped':
            return <IconMinus className="text-muted" />
        default:
            return <span className="inline-block size-4 rounded-full border border-primary" />
    }
}

/** The setup job's steps as they run. */
export const ContentAutopilotSetupProgress = ({ job }: { job: AEOSetupJobApi }): JSX.Element => (
    <ol className="m-0 flex list-none flex-col gap-2 p-0" data-attr="content-autopilot-setup-progress">
        {job.steps.map((step) => (
            <li key={step.step} className="flex items-center gap-2">
                <span className="flex w-5 shrink-0 justify-center text-base">
                    <StepIcon status={step.status} />
                </span>
                <span className="flex-1">{STEP_LABELS[step.step]}</span>
                <span className="text-xs text-secondary">{stepNote(step)}</span>
            </li>
        ))}
    </ol>
)
