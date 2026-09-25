import type { ChartTheme } from '@posthog/quill-charts'

import { formatPercentage } from 'lib/utils/numbers'

import { MCPProtocolVersionBreakdownItem } from '~/queries/schema/schema-general'

import { shadeColor } from './modelColors'

export const CURRENT_PROTOCOL_VERSION = '2026-07-28'

const MCP_SITE = 'https://modelcontextprotocol.io'
export const PROTOCOL_VERSIONING_URL = `${MCP_SITE}/docs/learn/versioning`

// Released spec versions, one line per release. Anything unlisted (junk values, a version
// released after this list) renders without a link rather than a 404.
const SPEC_VERSION_PATHS: Record<string, string> = {
    '2024-11-05': '/specification/2024-11-05',
    '2025-03-26': '/specification/2025-03-26/changelog',
    '2025-06-18': '/specification/2025-06-18/changelog',
    '2025-11-25': '/specification/2025-11-25/changelog',
    '2026-07-28': '/specification/2026-07-28/changelog',
    draft: '/specification/draft/changelog',
}

export function specVersionUrl(version: string): string | undefined {
    const path = SPEC_VERSION_PATHS[version]
    return path ? `${MCP_SITE}${path}` : undefined
}

type VersionGroup = 'current' | 'legacy' | 'unknown'

// The runner only folds legacy versions into 'Other', so it belongs to the legacy group.
export function versionGroup(row: MCPProtocolVersionBreakdownItem): VersionGroup {
    if (row.protocol_version === 'Unknown') {
        return 'unknown'
    }
    return row.is_current ? 'current' : 'legacy'
}

export function summarizeProtocolVersions(rows: MCPProtocolVersionBreakdownItem[]): {
    totalCalls: number
    unknownCalls: number
    legacyCalls: number
} {
    const sumCalls = (predicate: (row: MCPProtocolVersionBreakdownItem) => boolean): number =>
        rows.filter(predicate).reduce((total, row) => total + row.total_calls, 0)
    return {
        totalCalls: sumCalls(() => true),
        unknownCalls: sumCalls((row) => versionGroup(row) === 'unknown'),
        legacyCalls: sumCalls((row) => versionGroup(row) === 'legacy'),
    }
}

// Two significant digits round 99.6% up to "100%", which would read as nobody having migrated.
export function formatShare(pct: number): string {
    return pct >= 99.5 && pct < 100 ? '>99%' : formatPercentage(pct, { compact: true })
}

const GROUP_PALETTE_INDEX = { current: 0, legacy: 11 }
const SHADE_OFFSETS = [0, 14, -14, 28]
const OTHER_OPACITY = 0.45

export interface SegmentStyle {
    color: string | undefined
    opacity?: number
}

export function segmentStyles(theme: ChartTheme, rows: MCPProtocolVersionBreakdownItem[]): SegmentStyle[] {
    const shadeIndex = { current: 0, legacy: 0 }
    return rows.map((row) => {
        const group = versionGroup(row)
        if (group === 'unknown') {
            return { color: theme.axisColor }
        }
        const base = theme.colors[GROUP_PALETTE_INDEX[group]]
        if (row.protocol_version === 'Other') {
            return { color: shadeColor(base, 0) ?? theme.axisColor, opacity: OTHER_OPACITY }
        }
        const offset = SHADE_OFFSETS[shadeIndex[group]++ % SHADE_OFFSETS.length]
        return { color: shadeColor(base, offset) ?? theme.axisColor }
    })
}
