import { LemonTagType } from 'lib/lemon-ui/LemonTag'

import { DigestRunApi, DigestRunStatusEnumApi } from '../../generated/api.schemas'

const STATUS_DISPLAY: Record<DigestRunStatusEnumApi, { type: LemonTagType; label: string }> = {
    pending: { type: 'default', label: 'Pending' },
    completed: { type: 'success', label: 'Posted' },
    failed: { type: 'danger', label: 'Failed' },
}

/**
 * What happened to a digest run.
 *
 * A run that found nothing worth summarizing completes without calling Slack, and still stamps
 * posted_at. Only slack_message_ts proves a message exists, so it decides "Posted" against
 * "Nothing to post" — otherwise the table claims a Slack post the reader will not find.
 */
export function digestStatusDisplay(run: DigestRunApi): { type: LemonTagType; label: string } {
    if (run.status === DigestRunStatusEnumApi.Completed && !run.slack_message_ts) {
        return { type: 'muted', label: 'Nothing to post' }
    }
    return STATUS_DISPLAY[run.status] ?? { type: 'muted', label: run.status }
}

/**
 * Where a digest went, as a person would say it.
 *
 * slack_channel_name is display-only and can be blank, so the ID is the fallback — a run with
 * neither would otherwise render as an empty cell.
 */
export function digestDestinationLabel(run: DigestRunApi): string {
    return `#${run.slack_channel_name || run.slack_channel_id}`
}
