import { dayjs } from 'lib/dayjs'

import type { ToleratedHashEntryApi } from '../generated/api.schemas'
import { countRecentTolerations, shouldSuggestQuarantine } from './quarantineNudge'

const NOW = dayjs('2026-06-10T12:00:00Z')

function tolerations(reason: string, count: number, daysAgo: number): ToleratedHashEntryApi[] {
    return Array.from({ length: count }, (_, index) => ({
        id: `${reason}-${daysAgo}-${index}`,
        alternate_hash: `alt-${index}`,
        baseline_hash: 'base',
        reason,
        diff_percentage: 1,
        created_at: NOW.subtract(daysAgo, 'day').toISOString(),
        source_run_id: null,
    }))
}

describe('quarantineNudge', () => {
    it.each([
        { name: 'three manual in the window', hashes: tolerations('human', 3, 2), expected: true },
        {
            name: 'manual and agent add up',
            hashes: [...tolerations('human', 2, 2), ...tolerations('agent', 1, 5)],
            expected: true,
        },
        { name: 'two manual is not enough', hashes: tolerations('human', 2, 2), expected: false },
        { name: 'manual exactly at the window edge count', hashes: tolerations('human', 3, 30), expected: true },
        { name: 'manual outside the window do not count', hashes: tolerations('human', 3, 31), expected: false },
        {
            name: 'a few auto do not reach the manual bar',
            hashes: tolerations('auto_threshold', 9, 2),
            expected: false,
        },
        { name: 'ten auto in the window', hashes: tolerations('auto_threshold', 10, 2), expected: true },
        { name: 'no history', hashes: [], expected: false },
    ])('$name', ({ hashes, expected }) => {
        expect(shouldSuggestQuarantine(countRecentTolerations(hashes, NOW))).toBe(expected)
    })
})
