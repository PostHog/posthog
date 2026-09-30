import { PrStateEnumApi, TaskRunDetailDTOApi } from '../generated/api.schemas'

export type SpaceFeedStatusVariant = 'default' | 'info' | 'destructive' | 'success' | 'completed'

export interface SpaceFeedStatus {
    label: string
    variant: SpaceFeedStatusVariant
}

const RUN_STATUSES: Record<string, SpaceFeedStatus> = {
    not_started: { label: 'Not started', variant: 'default' },
    queued: { label: 'Queued', variant: 'default' },
    in_progress: { label: 'In progress', variant: 'info' },
    completed: { label: 'Ready', variant: 'success' },
    failed: { label: 'Failed', variant: 'destructive' },
    cancelled: { label: 'Cancelled', variant: 'default' },
}

// Once a PR exists its GitHub state is the card's status, with PostHog Desktop's labels and colors.
const PR_STATUSES: Record<Exclude<PrStateEnumApi, 'unknown'>, SpaceFeedStatus> = {
    open: { label: 'PR ready', variant: 'info' },
    draft: { label: 'Draft PR', variant: 'default' },
    merged: { label: 'Merged', variant: 'default' },
    closed: { label: 'Closed', variant: 'destructive' },
}

const TERMINAL_STATUSES = new Set(['completed', 'failed', 'cancelled'])

function hasPullRequest(output: TaskRunDetailDTOApi['output']): boolean {
    if (!output) {
        return false
    }
    const urls = Array.isArray(output.pr_urls) ? output.pr_urls : []
    return typeof output.pr_url === 'string' || urls.some((url) => typeof url === 'string')
}

export function spaceFeedStatus(
    run: TaskRunDetailDTOApi | null | undefined,
    prState?: PrStateEnumApi | null
): SpaceFeedStatus | null {
    if (!run) {
        return { label: 'Draft', variant: 'default' }
    }
    const stopped = run.status === 'failed' || run.status === 'cancelled'
    if (!stopped && hasPullRequest(run.output)) {
        return prState && prState !== 'unknown' ? PR_STATUSES[prState] : PR_STATUSES.open
    }
    if (run.environment !== 'cloud' && !TERMINAL_STATUSES.has(run.status)) {
        return null
    }
    return RUN_STATUSES[run.status] ?? null
}
