import type { InboxItem } from '@/model/types'

import { snoozeLabels } from './snoozeTimes'

// A `signals` snooze is server state (`state: potential`): the server hides the report until its `signal_count`
// reaches `threshold`. The device remembers it to label the row until the inbox list refetches without the report.
export type SnoozeEntry =
    | { kind: 'until'; until: string; at: string; notificationId?: string }
    | { kind: 'signals'; threshold: number | null; at: string }

/** A signal snooze label is dropped after this long, in case the device never sees the new count. */
export const SIGNAL_SNOOZE_MAX_MS = 14 * 24 * 60 * 60 * 1000

export function snoozeKey(scope: { host: string; projectId: number }, reportId: string): string {
    return `${scope.host}|${scope.projectId}|${reportId}`
}

export function isSnoozeActive(entry: SnoozeEntry, now: Date, signalCount?: number): boolean {
    if (entry.kind === 'until') {
        return new Date(entry.until).getTime() > now.getTime()
    }
    if (now.getTime() - new Date(entry.at).getTime() > SIGNAL_SNOOZE_MAX_MS) {
        return false
    }
    return entry.threshold === null || signalCount === undefined || signalCount < entry.threshold
}

/** Row text, computed against `now` so "tomorrow" becomes the time once the day comes. */
export function snoozeRowLabel(entry: SnoozeEntry, now: Date): string {
    if (entry.kind === 'signals') {
        return snoozeLabels({ kind: 'signals', count: 0 }, now).row
    }
    return snoozeLabels({ kind: 'until', preset: 'custom', until: entry.until }, now).row
}

/** Signal snoozes are kept until their age limit, because the count is unknown here. */
export function pruneSnoozes(entries: Record<string, SnoozeEntry>, now: Date): Record<string, SnoozeEntry> {
    return Object.fromEntries(Object.entries(entries).filter(([, entry]) => isSnoozeActive(entry, now)))
}

export function applySnoozes(
    items: readonly InboxItem[],
    entries: Record<string, SnoozeEntry>,
    scope: { host: string; projectId: number },
    now: Date,
    signalCounts: Record<string, number> = {}
): InboxItem[] {
    return items.map((item) => {
        const entry = entries[snoozeKey(scope, item.reportId)]
        if (!entry || item.state === 'done' || item.state === 'dismissed') {
            return item
        }
        if (!isSnoozeActive(entry, now, signalCounts[item.reportId])) {
            return item
        }
        return { ...item, state: 'snoozed', snoozeLabel: snoozeRowLabel(entry, now), needsInput: false }
    })
}
