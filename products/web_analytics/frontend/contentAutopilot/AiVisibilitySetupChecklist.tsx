import { IconCheck, IconMinus, IconX } from '@posthog/icons'
import { Spinner } from '@posthog/quill'

import type { AEOSetupJobApi, AEOSetupStepApi } from 'products/web_analytics/frontend/generated/api.schemas'

import type { EngineProgress } from './contentAutopilotSetupLogic'
import { engineLabel } from './utils'

type RowState = 'waiting' | 'running' | 'done' | 'skipped' | 'failed'

interface Row {
    key: string
    label: string
    state: RowState
    note: string
}

const STEP_LABELS: Record<AEOSetupStepApi['step'], string> = {
    brand: 'Saving your site as your brand',
    research: 'Reading your site to find your category and competitors',
    prompts: 'Writing prompts',
    keywords: 'Picking keywords',
    first_run: 'Queuing the first checks',
}

const SKIP_NOTES: Record<string, string> = {
    already_set: 'Already set up',
    already_run: 'Checks already ran',
    not_requested: 'Not requested',
    not_available: 'Not available for this project yet',
    nothing_to_run: 'Needs your brand and active prompts first',
    cancelled: 'Cancelled',
}

const stepRow = (step: AEOSetupStepApi): Row => {
    const added = step.added ?? 0
    const note =
        step.status === 'done'
            ? step.step === 'research'
                ? `Found ${added} competitor${added === 1 ? '' : 's'}`
                : step.step === 'prompts' || step.step === 'keywords'
                  ? `Added ${added}${step.requested && added < step.requested ? ` of ${step.requested}` : ''}`
                  : 'Done'
            : step.status === 'skipped'
              ? (SKIP_NOTES[step.detail ?? ''] ?? 'Skipped')
              : step.status === 'failed'
                ? step.detail || 'Failed'
                : step.status === 'running'
                  ? 'Working…'
                  : 'Waiting'
    const state: RowState = step.status === 'pending' ? 'waiting' : step.status
    return { key: step.step, label: STEP_LABELS[step.step], state, note }
}

const engineRow = (progress: EngineProgress, queued: boolean, checksRunning: boolean, stopRequested: boolean): Row => {
    const label = `Running ${engineLabel(progress.engine)} checks`
    const count = `${Math.min(progress.done, progress.expected)} of ${progress.expected}`
    if (!queued) {
        return { key: progress.engine, label, state: 'waiting', note: 'Waiting' }
    }
    if (checksRunning) {
        return {
            key: progress.engine,
            label,
            state: 'running',
            note: stopRequested ? `Stopping, ${count}` : count,
        }
    }
    return progress.done >= progress.expected
        ? { key: progress.engine, label, state: 'done', note: count }
        : { key: progress.engine, label, state: 'skipped', note: `Stopped at ${count}` }
}

const RowIcon = ({ state }: { state: RowState }): JSX.Element => {
    switch (state) {
        case 'done':
            return <IconCheck className="text-success-foreground" />
        case 'failed':
            return <IconX className="text-destructive-foreground" />
        case 'running':
            return <Spinner className="text-base" />
        case 'skipped':
            return <IconMinus className="text-muted-foreground" />
        default:
            return <span className="inline-block size-4 rounded-full border border-border" />
    }
}

export const AiVisibilitySetupChecklist = ({
    job,
    engineProgress,
    checksRunning,
    stopRequested,
}: {
    job: AEOSetupJobApi
    engineProgress: EngineProgress[]
    checksRunning: boolean
    stopRequested: boolean
}): JSX.Element => {
    const firstRun = job.steps.find((step) => step.step === 'first_run')
    const queued = firstRun?.status === 'done'
    const rows = [
        ...job.steps
            .filter((step) => step.status !== 'skipped' || step.detail !== 'not_requested')
            .filter((step) => !(step.step === 'first_run' && (queued || step.status === 'pending')))
            .map(stepRow),
        ...(firstRun?.status === 'skipped' || firstRun?.status === 'failed'
            ? []
            : engineProgress.map((progress) => engineRow(progress, queued, checksRunning, stopRequested))),
    ]

    return (
        <ol className="m-0 flex list-none flex-col gap-2 p-0" data-attr="ai-visibility-setup-checklist">
            {rows.map((row) => (
                <li key={row.key} className="flex items-center gap-2" data-state={row.state}>
                    <span className="flex w-5 shrink-0 justify-center text-base">
                        <RowIcon state={row.state} />
                    </span>
                    <span className={row.state === 'waiting' ? 'flex-1 text-muted-foreground' : 'flex-1'}>
                        {row.label}
                    </span>
                    <span className="text-xs text-muted-foreground tabular-nums">{row.note}</span>
                </li>
            ))}
        </ol>
    )
}
