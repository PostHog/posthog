import { BindLogic, useActions } from 'kea'
import { useState } from 'react'

import { LemonTabs, LemonTag } from '@posthog/lemon-ui'

import { JSONViewer } from 'lib/components/JSONViewer'
import { PropertiesTable } from 'lib/components/PropertiesTable'
import { TZLabel } from 'lib/components/TZLabel'

import { EventType, PropertyDefinitionType } from '~/types'

import { formatMs } from '../dashboard/formatters'
import { CapturedJson } from '../sessions/MCPToolCallRow'
import { sessionCallDrawerLogic } from '../sessions/sessionCallDrawerLogic'
import { SessionTimeline } from '../sessions/SessionDrawer'
import { toolCallSessionLogic } from '../sessions/toolCallSessionLogic'

type ToolCallTab = 'overview' | 'session' | 'properties' | 'raw'

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

function ToolCallSession({ sessionId, event }: { sessionId: string; event: EventType }): JSX.Element {
    const { openCall } = useActions(sessionCallDrawerLogic)
    return (
        <BindLogic logic={toolCallSessionLogic} props={{ sessionId, timestamp: event.timestamp }}>
            <div className="h-[calc(100dvh-12rem)] min-h-0">
                <SessionTimeline focusedEventId={event.uuid ?? event.id} onOpenToolCall={openCall} />
            </div>
        </BindLogic>
    )
}

/**
 * A tool call's event in a drawer, in one row of tabs: the MCP fields, its session, then every property.
 * Built from the event view's parts rather than the event view, which nests its own tabs.
 */
export function ToolCallEventView({
    event,
    showSession = false,
}: {
    event: EventType
    /** Off where the drawer already sits over the call's session. */
    showSession?: boolean
}): JSX.Element {
    const [tab, setTab] = useState<ToolCallTab>('overview')
    const sessionId: string | undefined = showSession ? event.properties?.$session_id : undefined
    return (
        <LemonTabs<ToolCallTab>
            activeKey={tab}
            onChange={setTab}
            tabs={[
                { key: 'overview', label: 'Overview', content: <ToolCallOverview event={event} /> },
                sessionId
                    ? {
                          key: 'session',
                          label: 'Session',
                          content: <ToolCallSession sessionId={sessionId} event={event} />,
                      }
                    : null,
                {
                    key: 'properties',
                    label: 'Properties',
                    content: (
                        <div className="ph-no-capture">
                            <PropertiesTable
                                type={PropertyDefinitionType.Event}
                                properties={event.properties}
                                useDetectedPropertyType
                                filterable
                                sortProperties
                                searchable
                                collapsible
                            />
                        </div>
                    ),
                },
                {
                    key: 'raw',
                    label: 'Raw',
                    content: (
                        <div className="ph-no-capture">
                            <JSONViewer
                                src={event}
                                name="event"
                                collapsed={1}
                                collapseStringsAfterLength={80}
                                sortKeys
                            />
                        </div>
                    ),
                },
            ]}
        />
    )
}
