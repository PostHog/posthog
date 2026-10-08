import { useMemo } from 'react'

import { type ChartTheme, type TooltipContext } from '@posthog/quill-charts'

import { LemonCard } from 'lib/lemon-ui/LemonCard'
import { Tooltip } from 'lib/lemon-ui/Tooltip'

import { MCPProtocolVersionBreakdownItem } from '~/queries/schema/schema-general'

import { ChartTooltip } from './ChartTooltip'
import { formatNumber } from './formatters'
import {
    CURRENT_PROTOCOL_VERSION,
    PROTOCOL_VERSIONING_URL,
    formatShare,
    specVersionUrl,
    summarizeProtocolVersions,
    versionColor,
} from './protocolVersions'
import { ShareBarChart, type ShareBarRow } from './ShareBarChart'

function protocolVersionLabel(version: string): string {
    return version === 'Other' ? 'Other versions' : version
}

function renderTooltip(ctx: TooltipContext<MCPProtocolVersionBreakdownItem & { share: number }>): JSX.Element | null {
    const row = ctx.seriesData[0]?.series.meta
    if (!row) {
        return null
    }
    return (
        <ChartTooltip
            title={protocolVersionLabel(row.protocol_version)}
            rows={[
                ['Calls', formatNumber(row.total_calls)],
                ['Share of all calls', formatShare(row.share)],
            ]}
        />
    )
}

function SummarySpan({
    tooltip,
    docLink,
    children,
}: {
    tooltip: string
    docLink?: string
    children: React.ReactNode
}): JSX.Element {
    return (
        <Tooltip title={tooltip} docLink={docLink}>
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
    const columns = useMemo<ShareBarRow<MCPProtocolVersionBreakdownItem>[][]>(() => {
        const chartRows = rows.map((row) => ({
            key: `${row.protocol_version}:${row.is_current}`,
            label: protocolVersionLabel(row.protocol_version),
            href: specVersionUrl(row.protocol_version),
            value: row.total_calls,
            color: versionColor(theme, row),
            meta: row,
        }))
        const half = Math.ceil(chartRows.length / 2)
        return [chartRows.slice(0, half), chartRows.slice(half)].filter((column) => column.length > 0)
    }, [rows, theme])
    const share = (calls: number): number => (totalCalls > 0 ? (calls / totalCalls) * 100 : 0)

    return (
        <LemonCard className="flex min-w-0 flex-col gap-1 bg-surface-secondary px-3 py-2" hoverEffect={false}>
            <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
                <h3 className="mb-0 text-sm font-medium">
                    <SummarySpan
                        tooltip={`MCP protocol versions are named by their release date. Clients and servers agree on one for each request. ${CURRENT_PROTOCOL_VERSION} removed the initialize handshake that older versions use. Select a version to read what changed in it.`}
                        docLink={PROTOCOL_VERSIONING_URL}
                    >
                        Calls by MCP protocol version
                    </SummarySpan>
                </h3>
                <div className="flex flex-wrap gap-3 text-xs text-secondary tabular-nums" translate="no">
                    <SummarySpan
                        tooltip={`Calls on versions older than ${CURRENT_PROTOCOL_VERSION}, plus values that aren't a known version. Calls on the draft version count as current.`}
                    >
                        {formatShare(share(legacyCalls))} on versions before {CURRENT_PROTOCOL_VERSION}
                    </SummarySpan>
                    <SummarySpan tooltip="These calls have no protocol version, usually because the server runs @posthog/mcp before 0.10.0 or posthog (Python) before 7.33.0. Upgrade the SDK to capture it.">
                        {formatShare(share(unknownCalls))} unknown
                    </SummarySpan>
                </div>
            </div>
            <div className="grid min-w-0 grid-cols-1 gap-x-8 @min-[48rem]/mcp-overview:grid-cols-2">
                {columns.map((column) => (
                    <ShareBarChart
                        key={column[0].key}
                        rows={column}
                        totalCalls={totalCalls}
                        theme={theme}
                        tooltip={renderTooltip}
                        label="Calls by MCP protocol version"
                        fitContent
                    />
                ))}
            </div>
        </LemonCard>
    )
}
