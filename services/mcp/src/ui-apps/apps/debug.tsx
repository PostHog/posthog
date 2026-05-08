import '../styles/tailwind.css'

import type { App } from '@modelcontextprotocol/ext-apps'
import { BookOpen, ExternalLink, Flag, History, Info, Plus, Settings as SettingsIcon, Trash2 } from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'
import { createRoot } from 'react-dom/client'

import { DataTable, type DataTableColumn, DescriptionList } from '@posthog/mcp-ui'
import {
    Badge,
    Button,
    Card,
    CardContent,
    CardDescription,
    CardFooter,
    CardHeader,
    CardTitle,
    Empty,
    EmptyDescription,
    EmptyHeader,
    EmptyMedia,
    EmptyTitle,
    Field,
    FieldDescription,
    FieldGroup,
    FieldLabel,
    Progress,
    ProgressLabel,
    ProgressValue,
    Separator,
    Spinner,
    Switch,
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
                    <span className="text-sm text-destructive-foreground">Error: {error.message}</span>
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
                                        <span className="text-xxs text-muted-foreground font-mono">#{call.id}</span>
                                    </div>
                                    <span className="text-xxs text-muted-foreground font-mono block mt-1">
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
                        Call the <code className="rounded-sm bg-muted px-1 py-0.5 text-xs">debug-mcp-ui-apps</code> tool
                        to see data here.
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
                                        <span className="text-xxs text-muted-foreground font-mono">
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

// -- Showcase tab --
//
// Single rich Quill composition that mocks a realistic product surface
// (a fictional "release dashboard"). Demonstrates how Card, Badge,
// Progress, Tooltip, Tabs, DataTable, Empty, Field, Switch, Button,
// DescriptionList, and Separator compose together — not as isolated
// component demos, but as a page a developer would actually build.
//
// All data here is fabricated; the goal is layout fidelity, not realism.

interface MockEvaluation {
    timestamp: string
    distinctId: string
    variant: string
    matched: boolean
}

const mockEvaluations: MockEvaluation[] = [
    { timestamp: '2 min ago', distinctId: 'user_8af2…', variant: 'treatment-a', matched: true },
    { timestamp: '4 min ago', distinctId: 'user_3c91…', variant: 'control', matched: true },
    { timestamp: '7 min ago', distinctId: 'user_b14e…', variant: 'treatment-b', matched: true },
    { timestamp: '12 min ago', distinctId: 'user_77d0…', variant: 'control', matched: false },
    { timestamp: '18 min ago', distinctId: 'user_e5a3…', variant: 'treatment-a', matched: true },
]

const evaluationColumns: DataTableColumn<MockEvaluation>[] = [
    { key: 'timestamp', header: 'When', sortable: true },
    {
        key: 'distinctId',
        header: 'Distinct ID',
        render: (row) => <span className="font-mono text-xs">{row.distinctId}</span>,
    },
    {
        key: 'variant',
        header: 'Variant',
        render: (row) => <Badge variant="info">{row.variant}</Badge>,
    },
    {
        key: 'matched',
        header: 'Matched',
        align: 'right',
        render: (row) => <Badge variant={row.matched ? 'success' : 'destructive'}>{row.matched ? 'Yes' : 'No'}</Badge>,
    },
]

function ShowcaseTab(): JSX.Element {
    const [enabled, setEnabled] = useState(true)
    const [autoArchive, setAutoArchive] = useState(false)

    return (
        <TooltipProvider>
            <div className="flex flex-col gap-4">
                {/* Header */}
                <div className="flex flex-wrap items-start gap-3">
                    <Flag className="h-5 w-5 shrink-0 text-muted-foreground mt-0.5" />
                    <div className="flex flex-col gap-1 flex-1 min-w-0">
                        <div className="flex items-center gap-2 flex-wrap">
                            <span className="text-lg font-semibold">acme-q3-onboarding</span>
                            <Badge variant="success">Live</Badge>
                            <Badge variant="info">v2.4</Badge>
                            <Tooltip>
                                <TooltipTrigger
                                    render={
                                        <Badge variant="warning">
                                            <Info className="h-3 w-3" data-icon="inline-start" />
                                            Recently changed
                                        </Badge>
                                    }
                                />
                                <TooltipContent side="bottom">Rollout updated 14 minutes ago</TooltipContent>
                            </Tooltip>
                        </div>
                        <span className="text-xs font-mono text-muted-foreground">flag_8af2c91e</span>
                    </div>
                    <div className="flex items-center gap-2 shrink-0">
                        <Button variant="outline" size="sm">
                            Edit
                        </Button>
                        <Button size="sm">View in PostHog</Button>
                    </div>
                </div>

                {/* Hero card — rollout summary */}
                <Card>
                    <CardHeader>
                        <CardTitle>Variant rollout</CardTitle>
                        <CardDescription>How traffic is currently distributed.</CardDescription>
                    </CardHeader>
                    <CardContent>
                        <div className="flex flex-col gap-3">
                            <Progress value={25} variant="default">
                                <ProgressLabel>control</ProgressLabel>
                                <ProgressValue />
                            </Progress>
                            <Progress value={55} variant="success">
                                <ProgressLabel>treatment-a</ProgressLabel>
                                <ProgressValue />
                            </Progress>
                            <Progress value={20} variant="warning">
                                <ProgressLabel>treatment-b</ProgressLabel>
                                <ProgressValue />
                            </Progress>
                        </div>
                    </CardContent>
                </Card>

                {/* Stats card */}
                <Card>
                    <CardHeader>
                        <CardTitle>Overview</CardTitle>
                    </CardHeader>
                    <CardContent>
                        <DescriptionList
                            columns={2}
                            items={[
                                { label: 'Created', value: 'Sep 14, 2025' },
                                { label: 'Last evaluated', value: '2 minutes ago' },
                                { label: 'Total exposures', value: '124,802' },
                                { label: 'Owner', value: 'platform-team' },
                                {
                                    label: 'Linked experiment',
                                    value: (
                                        // eslint-disable-next-line react/forbid-elements
                                        <a
                                            href="#"
                                            className="inline-flex items-center gap-1 text-primary hover:underline"
                                        >
                                            onboarding-flow-v3
                                            <ExternalLink className="h-3 w-3" />
                                        </a>
                                    ),
                                },
                                { label: 'Environments', value: 'production, staging' },
                            ]}
                        />
                    </CardContent>
                </Card>

                {/* Buttons — variants, sizes, icon-only, with-icon, disabled, loading */}
                <Card>
                    <CardHeader>
                        <CardTitle>Buttons</CardTitle>
                        <CardDescription>
                            Variants, sizes, and states from <code className="font-mono">@posthog/quill</code>'s{' '}
                            <code className="font-mono">Button</code>.
                        </CardDescription>
                    </CardHeader>
                    <CardContent>
                        <div className="flex flex-col gap-4">
                            <div className="flex flex-col gap-2">
                                <span className="text-xs text-muted-foreground">Variants</span>
                                <div className="flex flex-wrap items-center gap-2">
                                    <Button>Default</Button>
                                    <Button variant="primary">Primary</Button>
                                    <Button variant="outline">Outline</Button>
                                    <Button variant="destructive">Destructive</Button>
                                    <Button variant="link">Link</Button>
                                    <Button variant="link-muted">Link muted</Button>
                                </div>
                            </div>

                            <div className="flex flex-col gap-2">
                                <span className="text-xs text-muted-foreground">Sizes</span>
                                <div className="flex flex-wrap items-center gap-2">
                                    <Button size="xs">Extra small</Button>
                                    <Button size="sm">Small</Button>
                                    <Button size="default">Default</Button>
                                    <Button size="lg">Large</Button>
                                </div>
                            </div>

                            <div className="flex flex-col gap-2">
                                <span className="text-xs text-muted-foreground">Icon-only</span>
                                <div className="flex flex-wrap items-center gap-2">
                                    <Button size="icon-xs" aria-label="Add">
                                        <Plus />
                                    </Button>
                                    <Button size="icon-sm" aria-label="Add">
                                        <Plus />
                                    </Button>
                                    <Button size="icon" aria-label="Add">
                                        <Plus />
                                    </Button>
                                    <Button size="icon-lg" aria-label="Add">
                                        <Plus />
                                    </Button>
                                </div>
                            </div>

                            <div className="flex flex-col gap-2">
                                <span className="text-xs text-muted-foreground">With icon</span>
                                <div className="flex flex-wrap items-center gap-2">
                                    <Button>
                                        <Plus />
                                        Add variant
                                    </Button>
                                    <Button variant="outline">
                                        <SettingsIcon />
                                        Settings
                                    </Button>
                                    <Button variant="destructive">
                                        <Trash2 />
                                        Delete flag
                                    </Button>
                                </div>
                            </div>

                            <div className="flex flex-col gap-2">
                                <span className="text-xs text-muted-foreground">Disabled and loading</span>
                                <div className="flex flex-wrap items-center gap-2">
                                    <Button disabled>Disabled</Button>
                                    <Button variant="outline" disabled>
                                        Outline disabled
                                    </Button>
                                    <Button disabled>
                                        <Spinner />
                                        Saving…
                                    </Button>
                                </div>
                            </div>
                        </div>
                    </CardContent>
                </Card>

                {/* Inner tabs — Activity / Audit / Settings */}
                <Card>
                    <Tabs defaultValue="activity">
                        <TabsList className="px-3">
                            <TabsTrigger value="activity">Recent evaluations</TabsTrigger>
                            <TabsTrigger value="audit">Audit log</TabsTrigger>
                            <TabsTrigger value="settings">Settings</TabsTrigger>
                        </TabsList>
                        <TabsContent value="activity" className="px-4 pb-4">
                            <DataTable<MockEvaluation>
                                columns={evaluationColumns}
                                data={mockEvaluations}
                                pageSize={0}
                                emptyMessage="No evaluations yet"
                            />
                        </TabsContent>
                        <TabsContent value="audit" className="px-4 pb-4">
                            <Empty className="py-10">
                                <EmptyHeader>
                                    <EmptyMedia variant="icon">
                                        <History className="h-5 w-5" />
                                    </EmptyMedia>
                                    <EmptyTitle>No audit entries yet</EmptyTitle>
                                    <EmptyDescription>
                                        Changes to this flag will appear here. Audit history is retained for 90 days.
                                    </EmptyDescription>
                                </EmptyHeader>
                            </Empty>
                        </TabsContent>
                        <TabsContent value="settings" className="px-4 pb-4">
                            <FieldGroup>
                                <Field orientation="horizontal">
                                    <FieldLabel>Enabled</FieldLabel>
                                    <Switch checked={enabled} onCheckedChange={setEnabled} />
                                </Field>
                                <Separator />
                                <Field orientation="horizontal">
                                    <FieldLabel>Auto-archive after 30 days</FieldLabel>
                                    <Switch checked={autoArchive} onCheckedChange={setAutoArchive} />
                                </Field>
                                <Separator />
                                <Field>
                                    <FieldLabel>Description</FieldLabel>
                                    <FieldDescription>
                                        Q3 onboarding redesign — control keeps the legacy stepper, treatment-a uses the
                                        new progressive layout, treatment-b adds inline validation.
                                    </FieldDescription>
                                </Field>
                            </FieldGroup>
                        </TabsContent>
                    </Tabs>
                </Card>

                {/* Footer card with link */}
                <Card>
                    <CardContent>
                        <div className="flex items-center gap-3 flex-wrap">
                            <BookOpen className="h-4 w-4 shrink-0 text-muted-foreground" />
                            <span className="text-sm text-muted-foreground flex-1 min-w-0">
                                Learn how to roll feature flags out gradually without breaking experiments.
                            </span>
                            <Button
                                variant="link"
                                size="sm"
                                // eslint-disable-next-line react/forbid-elements
                                render={
                                    <a href="https://posthog.com/docs/feature-flags" target="_blank" rel="noreferrer" />
                                }
                            >
                                Read the docs
                                <ExternalLink className="ml-1 h-3 w-3" />
                            </Button>
                        </div>
                    </CardContent>
                    <CardFooter>
                        <span className="text-xs text-muted-foreground">Mock surface — none of this data is real.</span>
                    </CardFooter>
                </Card>
            </div>
        </TooltipProvider>
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
                <span className="text-sm text-muted-foreground">
                    SDK debug view, a realistic Quill composition, and the shared loading/error states.
                </span>
            </div>
            <Tabs defaultValue="debug">
                <TabsList>
                    <TabsTrigger value="debug">Debug</TabsTrigger>
                    <TabsTrigger value="showcase">Showcase</TabsTrigger>
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
                <TabsContent value="showcase">
                    <ShowcaseTab />
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
