import { dayjs } from 'lib/dayjs'

import type { FlakinessEntryApi } from '../generated/api.schemas'

function formatExpiry(expiresAt: string | null | undefined): { label: string; isOverdue: boolean } {
    if (!expiresAt) {
        return { label: 'no expiry', isOverdue: false }
    }
    const expiry = dayjs(expiresAt)
    if (expiry.isBefore(dayjs())) {
        return { label: `ran out ${dayjs().diff(expiry, 'day')}d ago`, isOverdue: true }
    }
    return { label: `runs out in ${expiry.diff(dayjs(), 'day')}d`, isOverdue: false }
}

export function QuarantineCell({ entry }: { entry: FlakinessEntryApi }): JSX.Element {
    if (!entry.quarantine) {
        return <span className="text-muted">—</span>
    }
    const expiry = formatExpiry(entry.quarantine.expires_at)
    const author = entry.quarantine.created_by
    return (
        <div className="text-xs max-w-48">
            <div>{entry.quarantine.reason || 'No reason given'}</div>
            <div className="text-[11px] text-muted mt-0.5">
                {author ? `${author.first_name || author.email} · ` : ''}
                <span className={expiry.isOverdue ? 'text-danger font-semibold' : 'font-semibold'}>{expiry.label}</span>
            </div>
        </div>
    )
}
