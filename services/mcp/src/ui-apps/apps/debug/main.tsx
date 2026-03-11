import '../../styles/tailwind.css'

import { useState } from 'react'
import { createRoot } from 'react-dom/client'

import {
    Badge,
    Card,
    DataTable,
    type DataTableColumn,
    Link,
    Select,
    Stack,
    Tabs,
    TabsContent,
    TabsList,
    TabsTrigger,
    Tooltip,
} from '@posthog/mosaic'

import { AppErrorState, AppLoadingState } from '../../components/AppWrapper'
import { useToolResult } from '../../hooks/useToolResult'
// -- Debug tab --
import type { UseToolResultReturn } from '../../hooks/useToolResult'

function DebugTab({
    data,
    isConnected,
    error,
    app,
}: Pick<UseToolResultReturn<unknown>, 'data' | 'isConnected' | 'error' | 'app'>): JSX.Element {
    const hostContext = app?.getHostContext()

    if (error) {
        return (
            <Card padding="md" className="border-danger/30 bg-danger/5">
                <span className="text-sm text-danger">Error: {error.message}</span>
            </Card>
        )
    }

    if (!isConnected) {
        return (
            <Card padding="md">
                <span className="text-sm text-text-secondary">Connecting to host...</span>
            </Card>
        )
    }

    return (
        <Stack gap="md">
            <Card padding="md" className="border-info/30 bg-info/5">
                <span className="text-sm text-info">Connected to host</span>
            </Card>

            <Stack gap="xs">
                <span className="text-sm font-medium text-text-secondary">Connection info</span>
                <pre className="rounded-md bg-bg-tertiary border border-border-primary p-3 text-xs font-mono overflow-auto max-h-48">
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
            </Stack>

            {data ? (
                <Stack gap="xs">
                    <span className="text-sm font-medium text-text-secondary">Tool result data</span>
                    <pre className="rounded-md bg-bg-tertiary border border-border-primary p-3 text-xs font-mono overflow-auto max-h-72">
                        {JSON.stringify(data, null, 2)}
                    </pre>
                </Stack>
            ) : (
                <Stack gap="xs">
                    <span className="text-sm font-medium text-text-secondary">Waiting for tool result</span>
                    <span className="text-sm text-text-secondary">
                        Call the <code className="rounded bg-bg-tertiary px-1 py-0.5 text-xs">debug-mcp-ui-apps</code>{' '}
                        tool to see data here.
                    </span>
                </Stack>
            )}
        </Stack>
    )
}

// -- Badge demo --

function BadgeDemo(): JSX.Element {
    return (
        <Stack gap="md">
            <span className="text-sm text-text-secondary">Variants</span>
            <div className="flex items-center gap-2 flex-wrap">
                <Badge variant="success">Active</Badge>
                <Badge variant="danger">Error</Badge>
                <Badge variant="warning">Warning</Badge>
                <Badge variant="info">Info</Badge>
                <Badge variant="neutral">Neutral</Badge>
            </div>
            <span className="text-sm text-text-secondary">Sizes</span>
            <div className="flex items-center gap-2">
                <Badge variant="info" size="sm">
                    Small
                </Badge>
                <Badge variant="info" size="md">
                    Medium
                </Badge>
            </div>
        </Stack>
    )
}

// -- Card demo --

function CardDemo(): JSX.Element {
    return (
        <Stack gap="md">
            <Card padding="sm">
                <span className="text-sm text-text-secondary">Small padding</span>
            </Card>
            <Card padding="md">
                <Stack gap="xs">
                    <span className="text-sm font-semibold text-text-primary">Default card</span>
                    <span className="text-sm text-text-secondary">
                        Cards group related content with a border and background.
                    </span>
                </Stack>
            </Card>
            <Card padding="lg">
                <span className="text-sm text-text-secondary">Large padding</span>
            </Card>
        </Stack>
    )
}

// -- Stack demo --

function StackDemo(): JSX.Element {
    const box = 'rounded-md bg-info/10 text-info text-xs font-medium px-3 py-2 text-center'
    return (
        <Stack gap="md">
            <span className="text-sm text-text-secondary">Column (default)</span>
            <Stack gap="sm">
                <div className={box}>Item 1</div>
                <div className={box}>Item 2</div>
                <div className={box}>Item 3</div>
            </Stack>
            <span className="text-sm text-text-secondary">Row</span>
            <Stack direction="row" gap="sm">
                <div className={box}>Item 1</div>
                <div className={box}>Item 2</div>
                <div className={box}>Item 3</div>
            </Stack>
            <span className="text-sm text-text-secondary">Row, space-between</span>
            <Stack direction="row" gap="sm" justify="between">
                <div className={box}>Left</div>
                <div className={box}>Right</div>
            </Stack>
        </Stack>
    )
}

// -- Tooltip demo --

function TooltipDemo(): JSX.Element {
    return (
        <Stack gap="md">
            <span className="text-sm text-text-secondary">Hover over items to see tooltips.</span>
            <div className="flex items-center gap-6 flex-wrap py-4">
                <Tooltip content="This appears above" position="top">
                    <span className="text-sm cursor-default border-b border-dashed border-text-secondary">
                        Top tooltip
                    </span>
                </Tooltip>
                <Tooltip content="This appears below" position="bottom">
                    <span className="text-sm cursor-default border-b border-dashed border-text-secondary">
                        Bottom tooltip
                    </span>
                </Tooltip>
                <Tooltip content="Tooltips work on any element">
                    <Badge variant="info">Hover me</Badge>
                </Tooltip>
            </div>
        </Stack>
    )
}

// -- Select demo --

function SelectDemo(): JSX.Element {
    const [viz, setViz] = useState('table')
    const [size, setSize] = useState('md')
    return (
        <Stack gap="md">
            <Stack gap="sm">
                <span className="text-sm text-text-secondary">Visualization picker</span>
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
                <span className="text-xs text-text-secondary">
                    Selected: <span className="font-medium text-text-primary">{viz}</span>
                </span>
            </Stack>
            <Stack gap="sm">
                <span className="text-sm text-text-secondary">Size variants</span>
                <div className="flex items-center gap-2">
                    <Select
                        value={size}
                        onChange={setSize}
                        size="sm"
                        options={[
                            { value: 'sm', label: 'Small' },
                            { value: 'md', label: 'Medium' },
                        ]}
                    />
                    <Select
                        value={size}
                        onChange={setSize}
                        size="md"
                        options={[
                            { value: 'sm', label: 'Small' },
                            { value: 'md', label: 'Medium' },
                        ]}
                    />
                </div>
            </Stack>
        </Stack>
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
            <Badge variant={row.active ? 'success' : 'neutral'} size="sm">
                {row.active ? 'Active' : 'Inactive'}
            </Badge>
        ),
    },
]

function DataTableDemo(): JSX.Element {
    return (
        <Stack gap="md">
            <span className="text-sm text-text-secondary">
                Sortable columns, pagination (5 per page), and custom cell rendering.
            </span>
            <DataTable columns={sampleColumns} data={sampleData} pageSize={5} />
        </Stack>
    )
}

// -- Link demo --

function LinkDemo(): JSX.Element {
    return (
        <Stack gap="md">
            <span className="text-sm text-text-secondary">
                Internal and external links with automatic external icon.
            </span>
            <Stack gap="sm">
                <Link href="https://posthog.com" external>
                    PostHog (external)
                </Link>
                <Link href="#" className="text-sm">
                    Internal link
                </Link>
                <Link href="https://posthog.com/docs" external className="text-xs">
                    Small external link
                </Link>
            </Stack>
        </Stack>
    )
}

// -- Tabs demo --

function TabsDemo(): JSX.Element {
    return (
        <Stack gap="md">
            <span className="text-sm text-text-secondary">
                Composable tabs using children: Tabs &gt; TabsList + TabsContent.
            </span>
            <Card padding="none">
                <Tabs defaultValue="overview">
                    <TabsList className="px-3">
                        <TabsTrigger value="overview">Overview</TabsTrigger>
                        <TabsTrigger value="details">Details</TabsTrigger>
                        <TabsTrigger value="settings">Settings</TabsTrigger>
                    </TabsList>
                    <TabsContent value="overview" className="px-4 pb-4">
                        <Card padding="sm" className="bg-bg-secondary">
                            <span className="text-sm text-text-secondary">Overview content goes here.</span>
                        </Card>
                    </TabsContent>
                    <TabsContent value="details" className="px-4 pb-4">
                        <Card padding="sm" className="bg-bg-secondary">
                            <span className="text-sm text-text-secondary">Details content goes here.</span>
                        </Card>
                    </TabsContent>
                    <TabsContent value="settings" className="px-4 pb-4">
                        <Card padding="sm" className="bg-bg-secondary">
                            <span className="text-sm text-text-secondary">Settings content goes here.</span>
                        </Card>
                    </TabsContent>
                </Tabs>
            </Card>
        </Stack>
    )
}

// -- App --

function DebugApp(): JSX.Element {
    const toolResult = useToolResult<unknown>({ appName: 'MCP Apps Debug' })

    return (
        <div className="p-4">
            <Stack gap="xs" className="mb-4">
                <span className="text-lg font-semibold text-text-primary">MCP Apps Debug</span>
                <span className="text-sm text-text-secondary">SDK debug view and Mosaic component showcase.</span>
            </Stack>
            <Tabs defaultValue="debug">
                <TabsList>
                    <TabsTrigger value="debug">Debug</TabsTrigger>
                    <TabsTrigger value="badge">Badge</TabsTrigger>
                    <TabsTrigger value="card">Card</TabsTrigger>
                    <TabsTrigger value="stack">Stack</TabsTrigger>
                    <TabsTrigger value="tooltip">Tooltip</TabsTrigger>
                    <TabsTrigger value="select">Select</TabsTrigger>
                    <TabsTrigger value="link">Link</TabsTrigger>
                    <TabsTrigger value="datatable">DataTable</TabsTrigger>
                    <TabsTrigger value="tabs">Tabs</TabsTrigger>
                    <TabsTrigger value="loading">Loading</TabsTrigger>
                    <TabsTrigger value="error">Error</TabsTrigger>
                </TabsList>
                <TabsContent value="debug">
                    <DebugTab {...toolResult} />
                </TabsContent>
                <TabsContent value="badge">
                    <BadgeDemo />
                </TabsContent>
                <TabsContent value="card">
                    <CardDemo />
                </TabsContent>
                <TabsContent value="stack">
                    <StackDemo />
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
