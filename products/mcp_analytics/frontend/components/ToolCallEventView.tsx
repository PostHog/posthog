import { useState } from 'react'

import { LemonTabs, LemonTag } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'

import { ExpandedEventRow } from '~/queries/nodes/DataTable/ExpandedEventRow'
import { EventType } from '~/types'

import { formatMs } from '../dashboard/formatters'
import { CapturedJson } from '../sessions/MCPToolCallRow'

type ToolCallTab = 'overview' | 'properties'

// The SDK sends payloads as an object or a JSON string.
function asJson(value: unknown): string {
    return value === undefined || value === null ? '' : typeof value === 'string' ? value : JSON.stringify(value)
}

function Field({ label, children }: { label: string; children: React.ReactNode }): JSX.Element | null {
    if (children === undefined || children === null || children === '') {
        return null
    }
    return (
        <>
            <dt className="text-xs text-secondary">{label}</dt>
            <dd className="m-0 min-w-0 break-words text-sm">{children}</dd>
        </>
    )
}

function ToolCallOverview({ event }: { event: EventType }): JSX.Element {
    const p = event.properties ?? {}
    const isError = p.$mcp_is_error === true || p.$mcp_is_error === 'true' || p.$mcp_is_error === 1
    return (
        // Intents, arguments and results are raw event data, so keep them out of autocapture and replay.
        <div className="ph-no-capture flex flex-col gap-4">
            <dl className="m-0 grid grid-cols-[max-content_1fr] items-baseline gap-x-6 gap-y-2">
                <Field label="Tool">
                    <span className="font-mono font-semibold">{p.$mcp_tool_name}</span>
                </Field>
                <Field label="Status">
                    {isError ? (
                        <LemonTag type="danger">{p.$mcp_error_type || 'Error'}</LemonTag>
                    ) : (
                        <LemonTag type="success">Success</LemonTag>
                    )}
                </Field>
                {isError ? (
                    <Field label="Error">
                        {p.$mcp_error_message ? (
                            <span className="font-mono text-danger">{p.$mcp_error_message}</span>
                        ) : null}
                    </Field>
                ) : null}
                <Field label="Duration">
                    {p.$mcp_duration_ms != null ? formatMs(Number(p.$mcp_duration_ms)) : null}
                </Field>
                <Field label="Client">{p.$mcp_client_name}</Field>
                <Field label="Model">
                    {p.$mcp_llm_model ? <span className="font-mono">{p.$mcp_llm_model}</span> : null}
                </Field>
                <Field label="Server">
                    {p.$mcp_server_name ? [p.$mcp_server_name, p.$mcp_server_version].filter(Boolean).join(' ') : null}
                </Field>
                <Field label="Session">
                    {p.$session_id ? <span className="font-mono">{p.$session_id}</span> : null}
                </Field>
                <Field label="Time">
                    <TZLabel time={event.timestamp} />
                </Field>
                <Field label="Intent">{p.$mcp_intent}</Field>
            </dl>
            <CapturedJson label="Input" json={asJson(p.$mcp_parameters)} property="$mcp_parameters" />
            <CapturedJson label="Output" json={asJson(p.$mcp_response)} property="$mcp_response" />
        </div>
    )
}

/** A tool call's event in a drawer: the MCP fields first, then every property. */
export function ToolCallEventView({ event }: { event: EventType }): JSX.Element {
    const [tab, setTab] = useState<ToolCallTab>('overview')
    return (
        <LemonTabs<ToolCallTab>
            activeKey={tab}
            onChange={setTab}
            tabs={[
                { key: 'overview', label: 'Overview', content: <ToolCallOverview event={event} /> },
                { key: 'properties', label: 'All properties', content: <ExpandedEventRow event={event} /> },
            ]}
        />
    )
}
