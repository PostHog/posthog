import { useActions, useValues } from 'kea'
import { memo, useRef } from 'react'

import { IconBolt, IconClock, IconRefresh, IconSearch, IconSparkles } from '@posthog/icons'
import {
    Button,
    InputGroup,
    InputGroupAddon,
    InputGroupInput,
    InputGroupText,
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
    Skeleton,
    Spinner,
} from '@posthog/quill-primitives'

import { Resizer } from 'lib/components/Resizer/Resizer'
import { ResizerLogicProps, resizerLogic } from 'lib/components/Resizer/resizerLogic'
import { TZLabel } from 'lib/components/TZLabel'
import { useWindowSize } from 'lib/hooks/useWindowSize'
import { cn } from 'lib/utils/css-classes'

import { panelLayoutLogic } from '~/layout/panel-layout/panelLayoutLogic'

import { McpDateFilter } from '../components/McpDateFilter'
import type { MCPSessionApi } from '../generated/api.schemas'
import { MCPSessionDetail } from './MCPSessionDetail'
import { type MCPSessionOrderBy, type MCPSessionSorting, mcpSessionsLogic, orderByParam } from './mcpSessionsLogic'
import { formatDuration, sessionDurationMs } from './utils'

const SORT_OPTIONS: { value: MCPSessionOrderBy; label: string }[] = [
    { value: '-session_start', label: 'Latest' },
    { value: 'session_start', label: 'Oldest' },
    { value: '-duration_seconds', label: 'Longest' },
    { value: '-tool_call_count', label: 'Most tool calls' },
]

function sortingToValue(sorting: MCPSessionSorting | null): MCPSessionOrderBy {
    return (orderByParam(sorting) ?? '-session_start') as MCPSessionOrderBy
}

function valueToSorting(value: MCPSessionOrderBy): MCPSessionSorting {
    const descending = value.startsWith('-')
    return {
        column: (descending ? value.slice(1) : value) as MCPSessionSorting['column'],
        order: descending ? -1 : 1,
    }
}

export function MCPSessionsPlaylist(): JSX.Element {
    const { sidePanelWidth } = useValues(panelLayoutLogic)
    const { isWindowLessThan } = useWindowSize({ widthOffset: sidePanelWidth })
    const isVerticalLayout = isWindowLessThan('xl')

    return (
        <div
            className={cn(
                'w-full h-[calc(100vh-13rem)] min-h-[25rem] flex',
                isVerticalLayout ? 'flex-col' : 'flex-row gap-2'
            )}
        >
            {isVerticalLayout ? <VerticalLayout /> : <HorizontalLayout />}
        </div>
    )
}

function HorizontalLayout(): JSX.Element {
    const listRef = useRef<HTMLDivElement>(null)

    const resizerLogicProps: ResizerLogicProps = {
        logicKey: 'mcp-sessions-list-horizontal',
        containerRef: listRef,
        persistent: true,
        placement: 'right',
    }
    const { desiredSize } = useValues(resizerLogic(resizerLogicProps))

    return (
        <>
            <div
                ref={listRef}
                className="relative flex flex-col shrink-0"
                // eslint-disable-next-line react/forbid-dom-props
                style={{ width: desiredSize ?? 320, minWidth: 'min-content', maxWidth: '50%' }}
            >
                <SessionsListPanel />
                <Resizer {...resizerLogicProps} visible={false} offset="0.25rem" handleClassName="rounded my-1" />
            </div>
            <SessionDetailPanel className="flex-1 min-w-0 h-full" />
        </>
    )
}

function VerticalLayout(): JSX.Element {
    const detailRef = useRef<HTMLDivElement>(null)

    const resizerLogicProps: ResizerLogicProps = {
        logicKey: 'mcp-sessions-detail-vertical',
        containerRef: detailRef,
        persistent: true,
        placement: 'bottom',
    }
    const { desiredSize } = useValues(resizerLogic(resizerLogicProps))

    return (
        <>
            <div
                ref={detailRef}
                className="relative shrink-0 pb-2"
                // eslint-disable-next-line react/forbid-dom-props
                style={{ height: desiredSize ?? 320, minHeight: 240 }}
            >
                <SessionDetailPanel className="h-full" />
                <Resizer {...resizerLogicProps} visible={false} offset="0.25rem" handleClassName="rounded mx-1" />
            </div>
            <div className="relative flex flex-col min-h-0 flex-1">
                <SessionsListPanel />
            </div>
        </>
    )
}

function SessionDetailPanel({ className }: { className?: string }): JSX.Element {
    return (
        <div
            className={cn('flex flex-col overflow-hidden rounded border border-primary bg-surface-primary', className)}
        >
            <MCPSessionDetail />
        </div>
    )
}

function SessionsListPanel(): JSX.Element {
    const { setFilters, setDateFilter, loadSessions, loadMoreSessions, setSorting, selectSession } =
        useActions(mcpSessionsLogic)
    const { sessions, sessionsLoading, filters, dateFilter, sorting, hasNext, selectedSessionId } =
        useValues(mcpSessionsLogic)

    return (
        <div className="flex flex-col h-full min-h-0 overflow-hidden rounded border border-primary bg-surface-primary">
            <div className="shrink-0 flex flex-col gap-2 border-b border-primary p-2">
                <div className="flex flex-col gap-2" data-quill>
                    <div className="flex items-center gap-2">
                        <InputGroup className="flex-1">
                            <InputGroupAddon align="inline-start">
                                <InputGroupText>
                                    <IconSearch />
                                </InputGroupText>
                            </InputGroupAddon>
                            <InputGroupInput
                                type="search"
                                placeholder="Search by session id, client, or tool"
                                onChange={(e) => setFilters({ search: e.target.value })}
                                value={filters.search}
                            />
                        </InputGroup>
                        <Button
                            variant="outline"
                            size="icon"
                            className="size-8"
                            onClick={() => loadSessions()}
                            disabled={sessionsLoading}
                            title="Reload sessions"
                        >
                            {sessionsLoading ? <Spinner /> : <IconRefresh />}
                        </Button>
                    </div>
                    <div className="flex items-center justify-between gap-1">
                        <McpDateFilter
                            dateFrom={dateFilter.dateFrom}
                            dateTo={dateFilter.dateTo}
                            onChange={(dateFrom, dateTo) => setDateFilter(dateFrom, dateTo)}
                            dataAttr="mcp-sessions-date-filter"
                        />
                        <Select
                            value={sortingToValue(sorting)}
                            onValueChange={(value) => setSorting(valueToSorting(value as MCPSessionOrderBy))}
                        >
                            <SelectTrigger data-attr="mcp-sessions-sort">
                                <SelectValue>
                                    {(value: MCPSessionOrderBy) =>
                                        SORT_OPTIONS.find((o) => o.value === value)?.label ?? value
                                    }
                                </SelectValue>
                            </SelectTrigger>
                            <SelectContent>
                                {SORT_OPTIONS.map((option) => (
                                    <SelectItem key={option.value} value={option.value}>
                                        {option.label}
                                    </SelectItem>
                                ))}
                            </SelectContent>
                        </Select>
                    </div>
                </div>
            </div>
            <div className="flex-1 min-h-0 overflow-y-auto" data-attr="mcp-sessions-list">
                {sessionsLoading && sessions.length === 0 ? (
                    <div className="flex flex-col gap-2 p-2" data-quill>
                        {Array.from({ length: 6 }).map((_, i) => (
                            <Skeleton key={i} className="h-12 w-full" />
                        ))}
                    </div>
                ) : sessions.length === 0 ? (
                    <div className="p-4 text-center text-sm text-secondary">No MCP sessions yet</div>
                ) : (
                    <>
                        <ul className="flex flex-col list-none pl-0 m-0 divide-y divide-primary">
                            {sessions.map((session) => (
                                <li key={session.session_id}>
                                    <MCPSessionPreview
                                        session={session}
                                        isActive={session.session_id === selectedSessionId}
                                        onSelect={selectSession}
                                    />
                                </li>
                            ))}
                        </ul>
                        {hasNext ? (
                            <div className="flex justify-center py-2" data-quill>
                                <Button
                                    variant="outline"
                                    size="sm"
                                    onClick={() => loadMoreSessions()}
                                    disabled={sessionsLoading}
                                >
                                    {sessionsLoading ? <Spinner /> : null}
                                    Load more
                                </Button>
                            </div>
                        ) : null}
                    </>
                )}
            </div>
        </div>
    )
}

// memo relies on stable identities: kea replaces the sessions array wholesale on load
// (so unchanged rows keep their reference) and selectSession is a stable bound action.
// A selector that maps or clones sessions would silently defeat this.
const MCPSessionPreview = memo(function MCPSessionPreview({
    session,
    isActive,
    onSelect,
}: {
    session: MCPSessionApi
    isActive: boolean
    onSelect: (sessionId: string) => void
}): JSX.Element {
    const personLabel = session.person_name || session.person_email
    const durationMs = sessionDurationMs(session.session_start, session.session_end)

    return (
        <button
            type="button"
            data-attr="mcp-session-preview"
            aria-pressed={isActive}
            onClick={() => onSelect(session.session_id)}
            className={cn(
                'w-full text-left cursor-pointer border-l-2 px-2 py-1.5 text-xs flex flex-col gap-1',
                isActive
                    ? 'border-l-accent bg-accent-highlight-secondary'
                    : 'border-l-transparent hover:bg-accent-highlight-secondary'
            )}
        >
            <div className="flex items-center justify-between gap-2">
                {personLabel ? (
                    <span className="font-medium truncate">{personLabel}</span>
                ) : (
                    <span className="font-mono text-secondary truncate">{session.distinct_id || 'unknown'}</span>
                )}
                <span className="shrink-0 text-secondary">
                    <TZLabel time={session.session_start} />
                </span>
            </div>
            <div className="flex items-center justify-between gap-2 text-secondary">
                <div className="flex items-center gap-2 min-w-0">
                    <span className="flex items-center gap-1 whitespace-nowrap">
                        <IconBolt />
                        {session.tool_calls}
                    </span>
                    {session.mcp_client_name ? (
                        <span className="flex items-center gap-1 truncate">
                            <IconSparkles className="shrink-0" />
                            <span className="truncate">{session.mcp_client_name}</span>
                        </span>
                    ) : null}
                </div>
                <span className="flex items-center gap-1 whitespace-nowrap shrink-0">
                    <IconClock />
                    {formatDuration(durationMs)}
                </span>
            </div>
        </button>
    )
})
