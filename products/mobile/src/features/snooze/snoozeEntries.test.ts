import type { InboxItem } from '@/model/types'

import { applySnoozes, type SnoozeEntry, snoozeKey } from './snoozeEntries'

// Local-time constructor arguments so the cases hold in any time zone.
const local = (m: number, d: number, h: number, min = 0): Date => new Date(2026, m - 1, d, h, min)
const SCOPE = { host: 'https://us.example.com', projectId: 2 }
const NOW = local(10, 9, 14, 31)

function row(reportId: string, overrides: Partial<InboxItem> = {}): InboxItem {
    return {
        id: reportId,
        reportId,
        title: 'Report',
        sourceProduct: 'error_tracking',
        sourceLabel: 'Error',
        sources: ['error_tracking'],
        accent: 'alert',
        createdAt: local(10, 9, 9).toISOString(),
        updatedAt: local(10, 9, 9).toISOString(),
        modelScore: null,
        state: 'open',
        needsInput: true,
        read: false,
        ...overrides,
    }
}

describe('snooze entries', () => {
    test.each<[string, SnoozeEntry, number | undefined, Partial<InboxItem>]>([
        [
            'time snooze until tomorrow',
            { kind: 'until', until: local(10, 10, 9).toISOString(), at: NOW.toISOString() },
            undefined,
            { state: 'snoozed', snoozeLabel: 'Snoozed until tomorrow', needsInput: false },
        ],
        [
            'time snooze that ended',
            { kind: 'until', until: local(10, 9, 14, 0).toISOString(), at: local(10, 9, 13).toISOString() },
            undefined,
            { state: 'open', needsInput: true },
        ],
        [
            'signal snooze below its threshold',
            { kind: 'signals', threshold: 17, at: NOW.toISOString() },
            12,
            { state: 'snoozed', snoozeLabel: 'Snoozed until more signals' },
        ],
        [
            'signal snooze whose signals arrived',
            { kind: 'signals', threshold: 17, at: NOW.toISOString() },
            17,
            { state: 'open' },
        ],
        [
            'signal snooze past its age limit',
            { kind: 'signals', threshold: 17, at: local(9, 20, 9).toISOString() },
            12,
            { state: 'open' },
        ],
    ])('%s', (_name, entry, signalCount, expected) => {
        const entries = { [snoozeKey(SCOPE, 'r1')]: entry }
        const [item] = applySnoozes(
            [row('r1')],
            entries,
            SCOPE,
            NOW,
            signalCount === undefined ? {} : { r1: signalCount }
        )
        expect(item).toMatchObject(expected)
    })

    test('scopes snoozes by project and leaves done rows alone', () => {
        const until = { kind: 'until', until: local(10, 10, 9).toISOString(), at: NOW.toISOString() } as const
        const entries = {
            [snoozeKey({ ...SCOPE, projectId: 3 }, 'r1')]: until,
            [snoozeKey(SCOPE, 'r2')]: until,
        }
        const items = applySnoozes([row('r1'), row('r2', { state: 'done' })], entries, SCOPE, NOW)
        expect(items.map((item) => item.state)).toEqual(['open', 'done'])
    })
})
