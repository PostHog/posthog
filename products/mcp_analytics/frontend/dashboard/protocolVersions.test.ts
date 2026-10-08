import { DEFAULT_CHART_COLORS } from '@posthog/quill-charts'

import { MCPProtocolVersionBreakdownItem } from '~/queries/schema/schema-general'

import { formatShare, specVersionUrl, summarizeProtocolVersions, versionColor, versionGroup } from './protocolVersions'

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
        expect(versionGroup(item)).toBe(expected)
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

    it('colors each group once, with Other as faded legacy and Unknown muted', () => {
        const colors = [
            row('2026-07-28', true),
            row('2025-06-18', false),
            row('Other', false),
            row('Unknown', false),
        ].map((item) => versionColor(theme, item))

        expect(colors[0]).toBe(versionColor(theme, row('draft', true)))
        expect(colors[1]).toBe(versionColor(theme, row('v2', false)))
        expect(new Set(colors).size).toBe(4)
        expect(colors[3]).toBe(theme.axisColor)
    })

    it.each([
        ['2024-11-05', 'https://modelcontextprotocol.io/specification/2024-11-05'],
        ['2025-06-18', 'https://modelcontextprotocol.io/specification/2025-06-18/changelog'],
        ['2026-07-28', 'https://modelcontextprotocol.io/specification/2026-07-28/changelog'],
        ['draft', 'https://modelcontextprotocol.io/specification/draft/changelog'],
        ['2026-01-26', undefined],
        ['v2', undefined],
        ['Other', undefined],
        ['Unknown', undefined],
    ])('links %s to %s', (version, expected) => {
        expect(specVersionUrl(version)).toBe(expected)
    })

    it('falls back to the axis color when the palette is too short', () => {
        expect(versionColor({ colors: [], axisColor: '#888888' }, row('2025-06-18', false))).toBe('#888888')
    })
})
