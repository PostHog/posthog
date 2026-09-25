import { MCPProtocolVersionBreakdownItem } from '~/queries/schema/schema-general'

export const CURRENT_PROTOCOL_REVISION = '2026-07-28'

export function summarizeProtocolVersions(rows: MCPProtocolVersionBreakdownItem[]): {
    totalCalls: number
    unknownCalls: number
    legacyCalls: number
} {
    const sumCalls = (predicate: (row: MCPProtocolVersionBreakdownItem) => boolean): number =>
        rows.filter(predicate).reduce((total, row) => total + row.total_calls, 0)
    return {
        totalCalls: sumCalls(() => true),
        unknownCalls: sumCalls((row) => row.protocol_version === 'Unknown'),
        legacyCalls: sumCalls((row) => !row.is_current && row.protocol_version !== 'Unknown'),
    }
}
