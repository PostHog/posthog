import '../styles/tailwind.css'

import type { App } from '@modelcontextprotocol/ext-apps'
import { useCallback, useEffect, useRef, useState } from 'react'
import { createRoot } from 'react-dom/client'

import { DataTable, type DataTableColumn } from '@posthog/mcp-ui'
import {
    Badge,
    Button,
    Card,
    CardContent,
    Tabs,
    TabsContent,
    TabsList,
    TabsTrigger,
    Tooltip,
    TooltipContent,
    TooltipProvider,
    TooltipTrigger,
} from '@posthog/quill'

import { AppErrorState, AppLoadingState } from '../components/AppWrapper'
import { Select } from '../components/charts'
import { useToolResult } from '../hooks/useToolResult'
import type { UseToolResultReturn } from '../hooks/useToolResult'

// -- Host message logging --

interface HostMessage {
    id: number
    timestamp: string
    data: unknown
}

let messageIdCounter = 0

function useHostMessageLog(): HostMessage[] {
    const [messages, setMessages] = useState<HostMessage[]>([])

    useEffect(() => {
        const handler = (event: MessageEvent): void => {
            const entry: HostMessage = {
                id: ++messageIdCounter,
                timestamp: new Date().toISOString(),
                data: event.data,
            }

            setMessages((prev) => {
                const updated = [...prev, entry]
                // Keep only last 1000 messages
                return updated.length > 1000 ? updated.slice(-1000) : updated
            })
        }

        window.addEventListener('message', handler)

        return () => window.removeEventListener('message', handler)
    }, [])

    return messages
}

// -- Tool call results tracking --

interface ToolCallEntry {
    id: number
    sentAt: string
    message: string
    status: 'pending' | 'success' | 'error'
    result?: unknown
    error?: string
    receivedAt?: string
}

let toolCallIdCounter = 0

// -- Debug tab state hook (lives in parent to survive tab switches) --

interface DebugTabState {
    toolCalls: ToolCallEntry[]
    isCalling: boolean
    hasNewMessages: boolean
    callDebugTool: () => void
    setHasNewMessages: (v: boolean) => void
}

function useDebugTabState(app: App | null, hostMessageCount: number): DebugTabState {
    const [toolCalls, setToolCalls] = useState<ToolCallEntry[]>([])
    const [isCalling, setIsCalling] = useState(false)
    const [hasNewMessages, setHasNewMessages] = useState(false)
    const [lastSeenCount, setLastSeenCount] = useState(hostMessageCount)

    useEffect(() => {
        if (hostMessageCount > lastSeenCount) {
            setHasNewMessages(true)
        }
    }, [hostMessageCount, lastSeenCount])

    const callDebugTool = useCallback(async () => {
        if (!app || isCalling) {
            return
        }

        const callId = ++toolCallIdCounter
        const sentAt = new Date().toISOString()
        const message = `Debug call #${callId} at ${sentAt}`

        const entry: ToolCallEntry = { id: callId, sentAt, message, status: 'pending' }
        setToolCalls((prev) => [...prev, entry])
        setIsCalling(true)

        try {
            const result = await app.callServerTool({
                name: 'debug-mcp-ui-apps',
                arguments: { message },
            })

            const receivedAt = new Date().toISOString()

            setToolCalls((prev) =>
                prev.map((c) => {
                    if (c.id !== callId) {
                        return c
                    }
                    const updated: ToolCallEntry = {
                        ...c,
                        status: result.isError ? 'error' : 'success',
                        result: result.structuredContent ?? result.content,
                        receivedAt,
                    }
                    if (result.isError) {
                        updated.error = 'Tool returned an error'
                    }
                    return updated
                })
            )
        } catch (e) {
            const receivedAt = new Date().toISOString()
            const errMsg = e instanceof Error ? e.message : String(e)
            console.error('[PostHog MCP Debug] Tool call error:', { callId, error: errMsg, receivedAt })

            setToolCalls((prev) =>
                prev.map((c) => (c.id === callId ? { ...c, status: 'error', error: errMsg, receivedAt } : c))
            )
        } finally {
            setIsCalling(false)
        }
    }, [app, isCalling])

    const dismissNewMessages = useCallback(() => {
        setHasNewMessages(false)
        setLastSeenCount(hostMessageCount)
    }, [hostMessageCount])

    return { toolCalls, isCalling, hasNewMessages, callDebugTool, setHasNewMessages: dismissNewMessages }
}

// -- Debug tab --

function DebugTab({
    data,
    isConnected,
    error,
    app,
    hostMessages,
    debugState,
}: Pick<UseToolResultReturn<unknown>, 'data' | 'isConnected' | 'error' | 'app'> & {
    hostMessages: HostMessage[]
    debugState: DebugTabState
}): JSX.Element {
    const hostContext = app?.getHostContext()
    const messagesContainerRef = useRef<HTMLDivElement>(null)
    const { toolCalls, isCalling, hasNewMessages, callDebugTool, setHasNewMessages } = debugState

    const handleMessagesScroll = useCallback(() => {
        const container = messagesContainerRef.current
        if (!container) {
            return
        }
        const isAtBottom = container.scrollHeight - container.scrollTop - container.clientHeight < 40
        if (isAtBottom) {
            setHasNewMessages(false)
        }
    }, [setHasNewMessages])

    if (error) {
        return (
            <Card>
                <CardContent>
                    <span className="text-sm text-destructive">Error: {error.message}</span>
                </CardContent>
            </Card>
        )
    }

    if (!isConnected) {
        return (
            <Card>
                <CardContent>
                    <span className="text-sm text-muted-foreground">Connecting to host...</span>
                </CardContent>
            </Card>
        )
    }

    return (
        <div className="flex flex-col gap-3">
            <Card>
                <CardContent>
                    <span className="text-sm">Connected to host</span>
                </CardContent>
            </Card>

            <div className="flex flex-col gap-1">
                <span className="text-sm font-medium text-muted-foreground">Connection info</span>
                <pre className="rounded-md border bg-muted p-3 text-xs font-mono overflow-auto max-h-48">
                    {JSON.stringify(
                        {
                            isConnected,
                            hasHostStyles: !!hostContext?.styles,
                            hasHostFonts: !!hostContext?.fonts,
                        },
                        null,
                        2
                    )}
                </pre>
            </div>

            <Card>
                <CardContent>
                    <div className="flex flex-col gap-2">
                        <div className="flex flex-row items-center justify-between">
                            <span className="text-sm font-medium text-muted-foreground">Call debug tool from app</span>
                            <Button onClick={callDebugTool} disabled={isCalling} size="sm">
                                {isCalling ? 'Calling...' : 'Call debug-mcp-ui-apps'}
                            </Button>
                        </div>
                        <span className="text-xs text-muted-foreground">
                            Each call includes a unique timestamp so you can identify it in the results.
                        </span>
                    </div>
                </CardContent>
            </Card>

            {toolCalls.length > 0 && (
                <div className="flex flex-col gap-1">
                    <span className="text-sm font-medium text-muted-foreground">
                        Tool call results ({toolCalls.length})
                    </span>
                    <div className="rounded-md border bg-muted p-3 overflow-auto max-h-96">
                        <div className="flex flex-col gap-1">
                            {toolCalls.map((call) => (
                                <div key={call.id} className="border-b pb-2 last:border-b-0">
                                    <div className="flex flex-row items-center gap-2">
                                        <Badge
                                            variant={
                                                call.status === 'success'
                                                    ? 'success'
                                                    : call.status === 'error'
                                                      ? 'destructive'
                                                      : 'warning'
                                            }
                                        >
                                            {call.status}
                                        </Badge>
                                        <span className="text-[10px] text-muted-foreground font-mono">#{call.id}</span>
                                    </div>
                                    <span className="text-[10px] text-muted-foreground font-mono block mt-1">
                                        Sent: {call.sentAt}
                                        {call.receivedAt && ` | Received: ${call.receivedAt}`}
                                    </span>
                                    <pre className="text-xs font-mono whitespace-pre-wrap break-all mt-1">
                                        {call.error
                                            ? call.error
                                            : call.result
                                              ? JSON.stringify(call.result, null, 2)
                                              : 'Waiting for response...'}
                                    </pre>
                                </div>
                            ))}
                        </div>
                    </div>
                </div>
            )}

            {data ? (
                <div className="flex flex-col gap-1">
                    <span className="text-sm font-medium text-muted-foreground">Tool result data (from host)</span>
                    <pre className="rounded-md border bg-muted p-3 text-xs font-mono overflow-auto max-h-72">
                        {JSON.stringify(data, null, 2)}
                    </pre>
                </div>
            ) : (
                <div className="flex flex-col gap-1">
                    <span className="text-sm font-medium text-muted-foreground">Waiting for tool result</span>
                    <span className="text-sm text-muted-foreground">
                        Call the <code className="rounded bg-muted px-1 py-0.5 text-xs">debug-mcp-ui-apps</code> tool to
                        see data here.
                    </span>
                </div>
            )}

            <div className="flex flex-col gap-1">
                <div className="flex flex-row items-center justify-between">
                    <span className="text-sm font-medium text-muted-foreground">
                        Host messages ({hostMessages.length})
                    </span>
                    <span className="text-xs text-muted-foreground">All messages logged to console</span>
                </div>
                <div className="relative">
                    <div
                        ref={messagesContainerRef}
                        onScroll={handleMessagesScroll}
                        className="rounded-md border bg-muted p-3 overflow-auto max-h-96"
                    >
                        {hostMessages.length === 0 ? (
                            <span className="text-xs text-muted-foreground">No messages received yet.</span>
                        ) : (
                            <div className="flex flex-col gap-1">
                                {hostMessages.map((msg) => (
                                    <div key={msg.id} className="border-b pb-2 last:border-b-0">
                                        <span className="text-[10px] text-muted-foreground font-mono">
                                            {msg.timestamp}
                                        </span>
                                        <pre className="text-xs font-mono whitespace-pre-wrap break-all mt-0.5">
                                            {JSON.stringify(msg.data, null, 2)}
                                        </pre>
                                    </div>
                                ))}
                            </div>
                        )}
                    </div>
                    {hasNewMessages && (
                        <Button
                            variant="primary"
                            size="xs"
                            onClick={() => {
                                const container = messagesContainerRef.current
                                if (container) {
                                    container.scrollTop = container.scrollHeight
                                }
                                setHasNewMessages(false)
                            }}
                            className="absolute bottom-2 left-1/2 -translate-x-1/2 animate-bounce shadow-md"
                        >
                            New messages below
                        </Button>
                    )}
                </div>
            </div>
        </div>
    )
}

// -- Badge demo --

function BadgeDemo(): JSX.Element {
    return (
        <div className="flex flex-col gap-3">
            <span className="text-sm text-muted-foreground">Variants</span>
            <div className="flex items-center gap-2 flex-wrap">
                <Badge variant="success">Active</Badge>
                <Badge variant="destructive">Error</Badge>
                <Badge variant="warning">Warning</Badge>
                <Badge variant="info">Info</Badge>
                <Badge>Default</Badge>
            </div>
        </div>
    )
}

// -- Card demo --

function CardDemo(): JSX.Element {
    return (
        <div className="flex flex-col gap-3">
            <Card>
                <CardContent className="p-3">
                    <span className="text-sm text-muted-foreground">Compact card</span>
                </CardContent>
            </Card>
            <Card>
                <CardContent>
                    <div className="flex flex-col gap-1">
                        <span className="text-sm font-semibold">Default card</span>
                        <span className="text-sm text-muted-foreground">
                            Cards group related content with a border and background.
                        </span>
                    </div>
                </CardContent>
            </Card>
        </div>
    )
}

// -- Tooltip demo --

function TooltipDemo(): JSX.Element {
    return (
        <TooltipProvider>
            <div className="flex flex-col gap-3">
                <span className="text-sm text-muted-foreground">Hover over items to see tooltips.</span>
                <div className="flex items-center gap-6 flex-wrap py-4">
                    <Tooltip>
                        <TooltipTrigger
                            render={
                                <span className="text-sm cursor-default border-b border-dashed border-muted-foreground">
                                    Top tooltip
                                </span>
                            }
                        />
                        <TooltipContent side="top">This appears above</TooltipContent>
                    </Tooltip>
                    <Tooltip>
                        <TooltipTrigger
                            render={
                                <span className="text-sm cursor-default border-b border-dashed border-muted-foreground">
                                    Bottom tooltip
                                </span>
                            }
                        />
                        <TooltipContent side="bottom">This appears below</TooltipContent>
                    </Tooltip>
                    <Tooltip>
                        <TooltipTrigger render={<Badge variant="info">Hover me</Badge>} />
                        <TooltipContent>Tooltips work on any element</TooltipContent>
                    </Tooltip>
                </div>
            </div>
        </TooltipProvider>
    )
}

// -- Select demo (chart-internal Select) --

function SelectDemo(): JSX.Element {
    const [viz, setViz] = useState('table')
    return (
        <div className="flex flex-col gap-3">
            <div className="flex flex-col gap-2">
                <span className="text-sm text-muted-foreground">Visualization picker (chart-internal Select)</span>
                {/* eslint-disable-next-line react/forbid-elements */}
                <Select
                    value={viz}
                    onChange={setViz}
                    options={[
                        { value: 'table', label: 'Table' },
                        { value: 'bar', label: 'Bar chart' },
                        { value: 'line', label: 'Line chart' },
                        { value: 'number', label: 'Big number' },
                    ]}
                />
                <span className="text-xs text-muted-foreground">
                    Selected: <span className="font-medium text-foreground">{viz}</span>
                </span>
            </div>
        </div>
    )
}

// -- DataTable demo --

interface SampleRow {
    name: string
    country: string
    events: number
    revenue: number | null
    active: boolean
}

const sampleData: SampleRow[] = [
    { name: 'Acme Corp', country: 'US', events: 14280, revenue: 52000, active: true },
    { name: 'Globex', country: 'UK', events: 8930, revenue: 31500, active: true },
    { name: 'Initech', country: 'US', events: 6210, revenue: null, active: false },
    { name: 'Umbrella', country: 'JP', events: 22450, revenue: 89000, active: true },
    { name: 'Hooli', country: 'US', events: 3100, revenue: 12500, active: true },
    { name: 'Pied Piper', country: 'US', events: 45670, revenue: 120000, active: true },
    { name: 'Stark Ind.', country: 'US', events: 18900, revenue: 75000, active: false },
    { name: 'Wayne Ent.', country: 'US', events: 29300, revenue: 95000, active: true },
    { name: 'Cyberdyne', country: 'JP', events: 7800, revenue: 28000, active: false },
    { name: 'Oscorp', country: 'US', events: 11200, revenue: 41000, active: true },
    { name: 'Wonka Ind.', country: 'UK', events: 5400, revenue: 19000, active: true },
    { name: 'Aperture', country: 'US', events: 16700, revenue: 63000, active: false },
]

const sampleColumns: DataTableColumn<SampleRow>[] = [
    { key: 'name', header: 'Company', sortable: true },
    { key: 'country', header: 'Country', sortable: true },
    { key: 'events', header: 'Events', align: 'right', sortable: true },
    { key: 'revenue', header: 'Revenue', align: 'right', sortable: true },
    {
        key: 'active',
        header: 'Status',
        render: (row) => (
            <Badge variant={row.active ? 'success' : 'default'}>{row.active ? 'Active' : 'Inactive'}</Badge>
        ),
    },
]

function DataTableDemo(): JSX.Element {
    return (
        <div className="flex flex-col gap-3">
            <span className="text-sm text-muted-foreground">
                Sortable columns, pagination (5 per page), and custom cell rendering.
            </span>
            <DataTable columns={sampleColumns} data={sampleData} pageSize={5} />
        </div>
    )
}

// -- Link demo --

function LinkDemo(): JSX.Element {
    return (
        <div className="flex flex-col gap-3">
            <span className="text-sm text-muted-foreground">
                External and internal links (plain &lt;a&gt; styled with Quill tokens + Button link variants).
            </span>
            <div className="flex flex-col gap-2 items-start">
                <a
                    href="https://posthog.com"
                    target="_blank"
                    rel="noreferrer"
                    className="inline-flex items-center gap-1 text-sm text-primary hover:underline"
                >
                    PostHog (external)
                </a>
                <a href="#" className="inline-flex items-center gap-1 text-sm text-primary hover:underline">
                    Internal link
                </a>
                <Button variant="link" size="sm" className="px-0">
                    Button styled as link
                </Button>
            </div>
        </div>
    )
}

// -- Tabs demo --

function TabsDemo(): JSX.Element {
    return (
        <div className="flex flex-col gap-3">
            <span className="text-sm text-muted-foreground">
                Composable tabs using children: Tabs &gt; TabsList + TabsContent.
            </span>
            <Card>
                <Tabs defaultValue="overview">
                    <TabsList className="px-3">
                        <TabsTrigger value="overview">Overview</TabsTrigger>
                        <TabsTrigger value="details">Details</TabsTrigger>
                        <TabsTrigger value="settings">Settings</TabsTrigger>
                    </TabsList>
                    <TabsContent value="overview" className="px-4 pb-4">
                        <Card>
                            <CardContent className="p-3">
                                <span className="text-sm text-muted-foreground">Overview content goes here.</span>
                            </CardContent>
                        </Card>
                    </TabsContent>
                    <TabsContent value="details" className="px-4 pb-4">
                        <Card>
                            <CardContent className="p-3">
                                <span className="text-sm text-muted-foreground">Details content goes here.</span>
                            </CardContent>
                        </Card>
                    </TabsContent>
                    <TabsContent value="settings" className="px-4 pb-4">
                        <Card>
                            <CardContent className="p-3">
                                <span className="text-sm text-muted-foreground">Settings content goes here.</span>
                            </CardContent>
                        </Card>
                    </TabsContent>
                </Tabs>
            </Card>
        </div>
    )
}

// -- App --

function DebugApp(): JSX.Element {
    const toolResult = useToolResult<unknown>({ appName: 'MCP Apps Debug' })
    const hostMessages = useHostMessageLog()
    const debugState = useDebugTabState(toolResult.app, hostMessages.length)

    return (
        <div className="p-4">
            <div className="mb-4 flex flex-col gap-1">
                <span className="text-lg font-semibold">MCP Apps Debug</span>
                <span className="text-sm text-muted-foreground">SDK debug view and Quill component showcase.</span>
            </div>
            <Tabs defaultValue="debug">
                <TabsList>
                    <TabsTrigger value="debug">Debug</TabsTrigger>
                    <TabsTrigger value="badge">Badge</TabsTrigger>
                    <TabsTrigger value="card">Card</TabsTrigger>
                    <TabsTrigger value="tooltip">Tooltip</TabsTrigger>
                    <TabsTrigger value="select">Select</TabsTrigger>
                    <TabsTrigger value="link">Link</TabsTrigger>
                    <TabsTrigger value="datatable">DataTable</TabsTrigger>
                    <TabsTrigger value="tabs">Tabs</TabsTrigger>
                    <TabsTrigger value="loading">Loading</TabsTrigger>
                    <TabsTrigger value="error">Error</TabsTrigger>
                </TabsList>
                <TabsContent value="debug">
                    <DebugTab
                        data={toolResult.data}
                        isConnected={toolResult.isConnected}
                        error={toolResult.error}
                        app={toolResult.app}
                        hostMessages={hostMessages}
                        debugState={debugState}
                    />
                </TabsContent>
                <TabsContent value="badge">
                    <BadgeDemo />
                </TabsContent>
                <TabsContent value="card">
                    <CardDemo />
                </TabsContent>
                <TabsContent value="tooltip">
                    <TooltipDemo />
                </TabsContent>
                <TabsContent value="select">
                    <SelectDemo />
                </TabsContent>
                <TabsContent value="link">
                    <LinkDemo />
                </TabsContent>
                <TabsContent value="datatable">
                    <DataTableDemo />
                </TabsContent>
                <TabsContent value="tabs">
                    <TabsDemo />
                </TabsContent>
                <TabsContent value="loading">
                    <AppLoadingState />
                </TabsContent>
                <TabsContent value="error">
                    <AppErrorState message="Something went wrong" />
                </TabsContent>
            </Tabs>
        </div>
    )
}

const container = document.getElementById('root')
if (container) {
    createRoot(container).render(<DebugApp />)
}
