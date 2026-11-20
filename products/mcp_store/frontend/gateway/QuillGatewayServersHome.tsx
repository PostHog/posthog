import { useActions, useValues } from 'kea'

import { IconPlus, IconServer } from '@posthog/icons'
import {
    Badge,
    Button,
    Empty,
    EmptyDescription,
    EmptyHeader,
    EmptyMedia,
    EmptyTitle,
    Heading,
    Input,
    Skeleton,
    Text,
    ToggleGroup,
    ToggleGroupItem,
} from '@posthog/quill'

import { GATEWAY_CATEGORY_LABELS, mcpGatewayLogic } from './mcpGatewayLogic'
import { QuillGatewayAddServerModal } from './QuillGatewayAddServerModal'
import { QuillGatewayConnectionModal } from './QuillGatewayConnectionModal'
import { QuillGatewayServerCard } from './QuillGatewayServerCard'
import { QuillGatewayServersLoadError } from './QuillGatewayServersLoadError'

const ALL_CATEGORIES = 'all'

export function QuillGatewayServersHome({
    onOpenServer,
}: { onOpenServer?: (serverId: string) => void } = {}): JSX.Element {
    const {
        canAddServers,
        filteredServers,
        servers,
        serversLoadFailed,
        serversLoading,
        templatesLoading,
        searchQuery,
        categoryFilter,
        categoryCounts,
        isAdmin,
        mergedServers,
    } = useValues(mcpGatewayLogic)
    const { loadServers, openAddServerModal, setSearchQuery, setCategoryFilter } = useActions(mcpGatewayLogic)

    const categories = Object.keys(GATEWAY_CATEGORY_LABELS).filter((category) => categoryCounts[category])

    const clearFilters = (): void => {
        setSearchQuery('')
        setCategoryFilter(null)
    }

    return (
        <div className="flex flex-col gap-4">
            <QuillGatewayAddServerModal />
            <QuillGatewayConnectionModal />

            <div className="flex flex-wrap items-start justify-between gap-4">
                <div className="flex flex-col gap-1">
                    <Heading size="sm" render={<h3 className="m-0" />}>
                        MCP servers
                    </Heading>
                    <Text size="xs" variant="muted" render={<p className="m-0" />}>
                        Connect tools for yourself, your teammates, and PostHog agents.
                    </Text>
                </div>
                <Button
                    variant="primary"
                    onClick={openAddServerModal}
                    disabledReason={canAddServers ? undefined : 'Only project admins can add MCP servers.'}
                >
                    <IconPlus />
                    Add server
                </Button>
            </div>

            <div className="flex flex-wrap items-center justify-between gap-2">
                <Text size="xs" variant="muted" render={<span className="m-0" />}>
                    {`${filteredServers.length} ${filteredServers.length === 1 ? 'server' : 'servers'}`}
                </Text>
                {(searchQuery || categoryFilter) && <Button onClick={clearFilters}>Clear filters</Button>}
            </div>

            <Input
                type="search"
                placeholder="Search MCP servers…"
                value={searchQuery}
                onChange={(event) => setSearchQuery(event.target.value)}
                aria-label="Search MCP servers"
            />

            <ToggleGroup
                value={[categoryFilter ?? ALL_CATEGORIES]}
                onValueChange={(next: string[]) => {
                    if (next.length === 0) {
                        return
                    }

                    setCategoryFilter(next[0] === ALL_CATEGORIES ? null : next[0])
                }}
                spacing={2}
                className="flex-wrap"
            >
                <ToggleGroupItem value={ALL_CATEGORIES}>
                    All
                    <Badge>{mergedServers.length}</Badge>
                </ToggleGroupItem>
                {categories.map((category) => (
                    <ToggleGroupItem key={category} value={category}>
                        {GATEWAY_CATEGORY_LABELS[category]}
                        <Badge>{categoryCounts[category]}</Badge>
                    </ToggleGroupItem>
                ))}
            </ToggleGroup>

            {serversLoadFailed && servers.length > 0 && <QuillGatewayServersLoadError onRetry={loadServers} />}

            {serversLoadFailed && servers.length === 0 ? (
                <QuillGatewayServersLoadError onRetry={loadServers} />
            ) : (serversLoading || templatesLoading) && filteredServers.length === 0 ? (
                <div className="flex flex-col gap-2" aria-label="Loading MCP servers">
                    <Skeleton className="h-16" />
                    <Skeleton className="h-16" />
                    <Skeleton className="h-16" />
                </div>
            ) : filteredServers.length === 0 ? (
                <Empty>
                    <EmptyHeader>
                        <EmptyMedia variant="icon">
                            <IconServer />
                        </EmptyMedia>
                        <EmptyTitle>No servers match.</EmptyTitle>
                        <EmptyDescription>
                            {isAdmin
                                ? 'Connect a server, or clear the search.'
                                : 'Try a different search, or ask an admin to add a server.'}
                        </EmptyDescription>
                    </EmptyHeader>
                </Empty>
            ) : (
                <div className="flex flex-col gap-2">
                    {filteredServers.map((server) => (
                        <QuillGatewayServerCard key={server.id} server={server} onOpenServer={onOpenServer} />
                    ))}
                </div>
            )}
        </div>
    )
}
