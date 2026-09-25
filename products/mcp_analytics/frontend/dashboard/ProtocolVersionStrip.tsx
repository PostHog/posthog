import { useMemo } from 'react'

import { type ChartTheme } from '@posthog/quill-charts'

import { LemonCard } from 'lib/lemon-ui/LemonCard'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { lightenDarkenColor, toOpaqueHex } from 'lib/utils/colors'
import { formatPercentage } from 'lib/utils/numbers'

import { MCPProtocolVersionBreakdownItem } from '~/queries/schema/schema-general'

import { ChartTooltip } from './ChartTooltip'
import { formatNumber } from './formatters'
import { CURRENT_PROTOCOL_REVISION, summarizeProtocolVersions } from './protocolVersions'

const SHADE_OFFSETS = [0, 16, -16, 32, -32]

function protocolVersionLabel(version: string): string {
    return version === 'Other' ? 'Other revisions' : version
}

// Current and legacy revisions each get one hue, shaded per revision, so the bar still reads as
// current | legacy | unknown while neighbouring segments stay distinguishable.
function segmentColors(theme: ChartTheme, rows: MCPProtocolVersionBreakdownItem[]): (string | undefined)[] {
    const shadeIndex = { current: 0, legacy: 0 }
    return rows.map((row) => {
        if (row.protocol_version === 'Other' || row.protocol_version === 'Unknown') {
            return theme.axisColor
        }
        const group = row.is_current ? 'current' : 'legacy'
        const base = toOpaqueHex(row.is_current ? theme.colors[0] : theme.colors[9])
        const shade = shadeIndex[group]++
        return /^#[\da-f]{6}$/i.test(base)
            ? lightenDarkenColor(base, SHADE_OFFSETS[shade % SHADE_OFFSETS.length])
            : base
    })
}

function SummarySpan({ tooltip, children }: { tooltip: string; children: React.ReactNode }): JSX.Element {
    return (
        <Tooltip title={tooltip}>
            <span tabIndex={0} className="cursor-help decoration-dotted underline underline-offset-2">
                {children}
            </span>
        </Tooltip>
    )
}

export function ProtocolVersionStrip({
    rows,
    theme,
}: {
    rows: MCPProtocolVersionBreakdownItem[]
    theme: ChartTheme
}): JSX.Element {
    const { totalCalls, unknownCalls, legacyCalls } = useMemo(() => summarizeProtocolVersions(rows), [rows])
    const colors = useMemo(() => segmentColors(theme, rows), [theme, rows])
    const share = (calls: number): number => (totalCalls > 0 ? (calls / totalCalls) * 100 : 0)

    return (
        <LemonCard className="flex min-w-0 flex-col gap-2 bg-surface-secondary px-3 py-2" hoverEffect={false}>
            <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
                <h3 className="mb-0 text-sm font-medium">Calls by protocol revision</h3>
                <div className="flex flex-wrap gap-3 text-xs text-secondary tabular-nums" translate="no">
                    <SummarySpan
                        tooltip={`Calls on revisions older than ${CURRENT_PROTOCOL_REVISION}, the stateless revision. Legacy revisions use the initialize handshake. The rolling draft counts as current.`}
                    >
                        {formatPercentage(share(legacyCalls), { compact: true })} before {CURRENT_PROTOCOL_REVISION}
                    </SummarySpan>
                    <SummarySpan tooltip="These calls have no protocol revision, usually because the server runs @posthog/mcp before 0.10.0 or posthog (Python) before 7.33.0.">
                        {formatPercentage(share(unknownCalls), { compact: true })} unknown
                    </SummarySpan>
                </div>
            </div>
            <div
                className="flex h-3 w-full overflow-hidden rounded-sm bg-fill-secondary"
                role="img"
                aria-label={`${formatPercentage(share(legacyCalls), { compact: true })} of calls before ${CURRENT_PROTOCOL_REVISION}`}
            >
                {rows.map((row, index) => (
                    <Tooltip
                        key={row.protocol_version}
                        title={
                            <ChartTooltip
                                title={protocolVersionLabel(row.protocol_version)}
                                rows={[
                                    ['Calls', formatNumber(row.total_calls)],
                                    ['Share of all calls', formatPercentage(share(row.total_calls), { compact: true })],
                                ]}
                            />
                        }
                    >
                        <div
                            className="h-full min-w-px"
                            style={{ width: `${share(row.total_calls)}%`, backgroundColor: colors[index] }}
                        />
                    </Tooltip>
                ))}
            </div>
            <ul className="m-0 flex list-none flex-wrap gap-x-4 gap-y-1 p-0 text-xs tabular-nums" translate="no">
                {rows.map((row, index) => (
                    <li key={row.protocol_version} className="flex items-center gap-1.5">
                        <span className="size-2 shrink-0 rounded-full" style={{ backgroundColor: colors[index] }} />
                        <span className="text-primary">{protocolVersionLabel(row.protocol_version)}</span>
                        <span className="text-secondary">
                            {formatPercentage(share(row.total_calls), { compact: true })} ·{' '}
                            {formatNumber(row.total_calls)}
                        </span>
                    </li>
                ))}
            </ul>
        </LemonCard>
    )
}
