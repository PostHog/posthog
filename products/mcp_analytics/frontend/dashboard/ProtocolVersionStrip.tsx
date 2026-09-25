import { useMemo } from 'react'

import { type ChartTheme } from '@posthog/quill-charts'

import { LemonCard } from 'lib/lemon-ui/LemonCard'
import { Link } from 'lib/lemon-ui/Link'
import { Tooltip } from 'lib/lemon-ui/Tooltip'

import { MCPProtocolVersionBreakdownItem } from '~/queries/schema/schema-general'

import { formatNumber } from './formatters'
import {
    CURRENT_PROTOCOL_VERSION,
    PROTOCOL_VERSIONING_URL,
    formatShare,
    segmentStyles,
    specVersionUrl,
    summarizeProtocolVersions,
} from './protocolVersions'

function protocolVersionLabel(version: string): string {
    return version === 'Other' ? 'Other versions' : version
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

function VersionLabel({ version }: { version: string }): JSX.Element {
    const url = specVersionUrl(version)
    const label = protocolVersionLabel(version)
    return url ? (
        <Link to={url} target="_blank" className="text-primary">
            {label}
        </Link>
    ) : (
        <span className="text-primary">{label}</span>
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
    const styles = useMemo(() => segmentStyles(theme, rows), [theme, rows])
    const share = (calls: number): number => (totalCalls > 0 ? (calls / totalCalls) * 100 : 0)
    const key = (row: MCPProtocolVersionBreakdownItem): string => `${row.protocol_version}:${row.is_current}`

    return (
        <LemonCard className="flex min-w-0 flex-col gap-2 bg-surface-secondary px-3 py-2" hoverEffect={false}>
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
            <div className="flex h-3 w-full gap-px overflow-hidden rounded-sm" aria-hidden>
                {rows.map((row, index) => (
                    <div
                        key={key(row)}
                        className="h-full min-w-px"
                        style={{
                            width: `${share(row.total_calls)}%`,
                            backgroundColor: styles[index].color,
                            opacity: styles[index].opacity,
                        }}
                    />
                ))}
            </div>
            <ul className="m-0 flex list-none flex-wrap gap-x-4 gap-y-1 p-0 text-xs tabular-nums" translate="no">
                {rows.map((row, index) => (
                    <li key={key(row)} className="flex items-center gap-1.5">
                        <span
                            className="size-2 shrink-0 rounded-full"
                            style={{ backgroundColor: styles[index].color, opacity: styles[index].opacity }}
                        />
                        <VersionLabel version={row.protocol_version} />
                        <span className="text-secondary">
                            {formatShare(share(row.total_calls))} · {formatNumber(row.total_calls)}
                        </span>
                    </li>
                ))}
            </ul>
        </LemonCard>
    )
}
