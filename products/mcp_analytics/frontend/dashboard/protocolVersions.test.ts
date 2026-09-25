import { DEFAULT_CHART_COLORS } from '@posthog/quill-charts'

import { MCPProtocolVersionBreakdownItem } from '~/queries/schema/schema-general'

import { formatShare, revisionGroup, segmentStyles, summarizeProtocolVersions } from './protocolVersions'

const theme = { colors: [...DEFAULT_CHART_COLORS], axisColor: '#888888' }

const row = (protocol_version: string, is_current: boolean, total_calls = 1): MCPProtocolVersionBreakdownItem => ({
    protocol_version,
    is_current,
    total_calls,
})

describe('protocol versions', () => {
    it.each([
        [row('draft', true), 'current'],
        [row('2026-07-28', true), 'current'],
        [row('2025-06-18', false), 'legacy'],
        [row('v2', false), 'legacy'],
        [row('Other', false), 'legacy'],
        [row('Unknown', false), 'unknown'],
    ])('groups %o as %s', (item, expected) => {
        expect(revisionGroup(item)).toBe(expected)
    })

    it.each([
        { name: 'empty', rows: [], expected: { totalCalls: 0, unknownCalls: 0, legacyCalls: 0 } },
        {
            name: 'mixed eras',
            rows: [
                row('draft', true, 5),
                row('2026-07-28', true, 50),
                row('2025-06-18', false, 100),
                row('v2', false, 15),
                row('Other', false, 20),
                row('Unknown', false, 40),
            ],
            expected: { totalCalls: 230, unknownCalls: 40, legacyCalls: 135 },
        },
    ])('sums calls for $name', ({ rows, expected }) => {
        expect(summarizeProtocolVersions(rows)).toEqual(expected)
    })

    it.each([
        [0, '0%'],
        [0.4, '0.4%'],
        [61.2, '61%'],
        [99.4, '99%'],
        [99.6, '>99%'],
        [100, '100%'],
    ])('formats a %s%% share as %s', (pct, expected) => {
        expect(formatShare(pct)).toBe(expected)
    })

    it('keeps current, legacy, Other, and Unknown visually distinct', () => {
        const rows = [
            row('draft', true),
            row('2026-07-28', true),
            ...['2025-11-25', '2025-06-18', '2025-03-26', '2024-11-05'].map((v) => row(v, false)),
            row('Other', false),
            row('Unknown', false),
        ]

        const styles = segmentStyles(theme, rows)

        const colors = styles.map((style) => style.color)
        expect(new Set(colors.slice(0, 6)).size).toBe(6)
        expect(styles[6]).toEqual({ color: styles[2].color, opacity: 0.45 })
        expect(styles[7]).toEqual({ color: theme.axisColor })
    })

    it('falls back to the axis color when the palette is too short', () => {
        expect(segmentStyles({ colors: [], axisColor: '#888888' }, [row('2025-06-18', false)])).toEqual([
            { color: '#888888' },
        ])
    })
})
