import { LemonTagType } from '@posthog/lemon-ui'

import { TaskRunDetailDTOApi } from '../generated/api.schemas'

export interface SpaceFeedStatus {
    label: string
    type: LemonTagType
}

const RUN_STATUSES: Record<string, SpaceFeedStatus> = {
    not_started: { label: 'Not started', type: 'default' },
    queued: { label: 'Queued', type: 'default' },
    in_progress: { label: 'In progress', type: 'primary' },
    completed: { label: 'Ready', type: 'success' },
    failed: { label: 'Failed', type: 'danger' },
    cancelled: { label: 'Cancelled', type: 'muted' },
}

const TERMINAL_STATUSES = new Set(['completed', 'failed', 'cancelled'])

function hasPullRequest(output: TaskRunDetailDTOApi['output']): boolean {
    if (!output) {
        return false
    }
    const urls = Array.isArray(output.pr_urls) ? output.pr_urls : []
    return typeof output.pr_url === 'string' || urls.some((url) => typeof url === 'string')
}

export function spaceFeedStatus(run: TaskRunDetailDTOApi | null | undefined): SpaceFeedStatus | null {
    if (!run) {
        return { label: 'Draft', type: 'default' }
    }
    const stopped = run.status === 'failed' || run.status === 'cancelled'
    if (!stopped && hasPullRequest(run.output)) {
        return { label: 'PR ready', type: 'highlight' }
    }
    if (run.environment !== 'cloud' && !TERMINAL_STATUSES.has(run.status)) {
        return null
    }
    return RUN_STATUSES[run.status] ?? null
}
