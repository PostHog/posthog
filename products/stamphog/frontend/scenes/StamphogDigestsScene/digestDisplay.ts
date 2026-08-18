import { LemonTagType } from 'lib/lemon-ui/LemonTag'

import { DigestChannelApi, DigestRunStatusEnumApi } from '../../generated/api.schemas'

const STATUS_DISPLAY: Record<DigestRunStatusEnumApi, { type: LemonTagType; label: string }> = {
    pending: { type: 'default', label: 'Pending' },
    completed: { type: 'success', label: 'Posted' },
    failed: { type: 'danger', label: 'Failed' },
}

export function digestStatusDisplay(status: DigestRunStatusEnumApi): { type: LemonTagType; label: string } {
    return STATUS_DISPLAY[status] ?? { type: 'muted', label: status }
}

/**
 * Where a digest went, as a person would say it.
 *
 * slack_channel_name is display-only and can be blank on a channel resolved by ID, so the ID is the
 * fallback — a row with neither would otherwise render as an empty cell.
 */
export function digestChannelLabel(channel: DigestChannelApi): string {
    return `#${channel.slack_channel_name || channel.slack_channel_id}`
}
