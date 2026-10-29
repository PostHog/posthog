import type { DashboardBasicApi } from '@/api/dashboards'
import type { FileSystemShortcutApi } from '@/api/shortcuts'

import { mergeRecent, pinsFromShortcuts } from './viewPins'

function row(id: string, type: string, ref: string | null, order: number, extra: Partial<FileSystemShortcutApi> = {}) {
    return {
        id,
        path: `Name ${id}`,
        type,
        ref,
        href: null,
        order,
        created_at: '2026-10-01T10:00:00Z',
        ...extra,
    } satisfies FileSystemShortcutApi
}

describe('view pins', () => {
    test('puts ranked pins first and appends new pins in server order', () => {
        const rows = [
            row('a', 'dashboard', '1', 0),
            row('b', 'insight', 'abc', 1),
            row('c', 'web_analytics', null, 2),
            row('d', 'notebook', 'nb1', 3),
        ]

        const pins = pinsFromShortcuts(rows, { rank: { c: 0, a: 1 }, display: {} })

        expect(pins.map((pin) => pin.shortcutId)).toEqual(['c', 'a', 'b', 'd'])
        expect(pins.map((pin) => pin.native)).toEqual([true, true, true, false])
    })

    test('collapses rows for one view and keeps the ranked row, else the lowest order', () => {
        const rows = [
            row('old', 'dashboard', '7', 1, { created_at: '2026-09-01T10:00:00Z' }),
            row('sibling', 'dashboard', '7', 0, { created_at: '2026-10-01T10:00:00Z' }),
            row('ranked', 'insight', 'xyz', 5),
            row('renamed', 'insight', 'xyz', 2),
            row('product', 'web_analytics', null, 3),
            row('product-again', 'web_analytics', null, 4, { href: '/web' }),
            row('folder', 'folder', null, 6),
        ]

        const pins = pinsFromShortcuts(rows, { rank: { ranked: 0 }, display: {} })

        expect(pins.map((pin) => [pin.shortcutId, pin.shortcutIds])).toEqual([
            ['ranked', ['ranked', 'renamed']],
            ['sibling', ['old', 'sibling']],
            ['product', ['product', 'product-again']],
        ])
    })

    test('merges recent views newest first without duplicates, pins or never-viewed dashboards', () => {
        const server: DashboardBasicApi[] = [
            { id: 1, name: 'Growth', last_viewed_at: '2026-10-14T09:00:00Z' },
            { id: 2, name: 'Never opened', last_viewed_at: null },
            { id: 3, name: 'Pinned', last_viewed_at: '2026-10-14T11:00:00Z' },
        ]
        const device = [
            { kind: 'dashboard' as const, ref: '1', name: 'Growth', viewedAt: '2026-10-14T10:00:00Z' },
            { kind: 'insight' as const, ref: 'abc', name: 'Signups', viewedAt: '2026-10-13T10:00:00Z' },
        ]

        const recent = mergeRecent(device, server, new Set(['dashboard:3']))

        expect(recent.map((view) => [view.kind, view.ref, view.source])).toEqual([
            ['dashboard', '1', 'device'],
            ['insight', 'abc', 'device'],
        ])
    })
})
