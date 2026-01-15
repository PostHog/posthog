import classNames from 'classnames'
import clsx from 'clsx'
import React, { useEffect, useRef, useState } from 'react'
import { useDebouncedCallback } from 'use-debounce'

import { IconSearch } from '@posthog/icons'
import { LemonDivider, LemonInput, LemonTag, LemonTagProps, Tooltip } from '@posthog/lemon-ui'

import { pluralize } from 'lib/utils'

import { LLMTrace, LLMTraceEvent } from '~/queries/schema/schema-general'

import { SearchHighlight } from '../SearchHighlight'
import { EnrichedTraceTreeNode } from '../llmAnalyticsTraceDataLogic'
import {
    formatLLMCost,
    formatLLMEventTitle,
    formatLLMLatency,
    formatLLMUsage,
    getEventType,
    isLLMEvent,
} from '../utils'

// TreeNode types
export interface TreeNodeBaseProps {
    node:
        | EnrichedTraceTreeNode
        | { event: LLMTrace; displayTotalCost: number; displayLatency: number; displayUsage: string | null }
    isSelected: boolean
    onSelect: (eventId: string) => void
    searchQuery?: string
    showBillingInfo?: boolean
    eventTypeExpanded: (eventType: string) => boolean
}

// TreeNodeChildren types
export interface TreeNodeChildrenBaseProps {
    tree: EnrichedTraceTreeNode[]
    selectedEventId?: string | null
    onSelect: (eventId: string) => void
    searchQuery?: string
    showBillingInfo?: boolean
    eventTypeExpanded: (eventType: string) => boolean
}

// TraceSidebar types
export interface TraceSidebarBaseProps {
    trace: LLMTrace
    tree: EnrichedTraceTreeNode[]
    selectedEventId?: string | null
    searchQuery: string
    searchOccurrencesCount?: number
    onSearchChange: (query: string) => void
    onSelectEvent: (eventId: string) => void
    eventTypeExpanded: (eventType: string) => boolean
    showBillingInfo?: boolean
    eventTypeFiltersSlot?: React.ReactNode
}

export function EventTypeTag({
    event,
    size,
}: {
    event: LLMTrace | LLMTraceEvent
    size?: LemonTagProps['size']
}): JSX.Element {
    const eventType = getEventType(event)
    let tagType: LemonTagProps['type'] = 'completion'

    switch (eventType) {
        case 'generation':
            tagType = 'success'
            break
        case 'embedding':
            tagType = 'warning'
            break
        case 'span':
            tagType = 'default'
            break
        case 'trace':
            tagType = 'completion'
            break
    }

    return (
        <LemonTag className="uppercase" type={tagType} size={size}>
            {eventType}
        </LemonTag>
    )
}

export function renderModelRow(event: LLMTrace | LLMTraceEvent, searchQuery?: string): React.ReactNode | null {
    if (isLLMEvent(event)) {
        if (event.event === '$ai_generation') {
            if (!event.properties.$ai_span_name) {
                return null
            }

            let model = event.properties.$ai_model

            if (event.properties.$ai_provider) {
                model = `${model} (${event.properties.$ai_provider})`
            }

            return searchQuery?.trim() ? (
                <SearchHighlight string={model} substring={searchQuery} className="flex-1" />
            ) : (
                <span className="flex-1 truncate"> {model} </span>
            )
        }
    }

    return null
}

export function NestingGroup({
    onToggle,
    isCollapsed,
    children,
}: {
    onToggle?: () => void
    isCollapsed?: boolean
    children: React.ReactNode
}): JSX.Element {
    return (
        <li className={clsx('flex items-stretch min-w-0', isCollapsed && 'text-border hover:text-muted')}>
            <div
                className={clsx('mb-1 ml-1 cursor-pointer', !isCollapsed && 'text-border hover:text-muted')}
                onClick={onToggle}
            >
                <div
                    className={clsx(
                        'w-0 h-full my-0 ml-1 mr-2 border-l border-current',
                        isCollapsed && 'border-dashed'
                    )}
                />
            </div>
            <ul className="flex-1 min-w-0">{children}</ul>
        </li>
    )
}

export const TreeNodeBase = React.memo(function TreeNodeBase({
    node,
    isSelected,
    onSelect,
    searchQuery,
    showBillingInfo,
    eventTypeExpanded,
}: TreeNodeBaseProps): JSX.Element {
    const totalCost = node.displayTotalCost
    const latency = node.displayLatency
    const usage = node.displayUsage
    const item = node.event

    const eventType = getEventType(item)
    const isCollapsedDueToFilter = !eventTypeExpanded(eventType)
    const isBillable =
        showBillingInfo &&
        isLLMEvent(item) &&
        (item as LLMTraceEvent).event === '$ai_generation' &&
        !!(item as LLMTraceEvent).properties?.$ai_billable

    const children = [
        isLLMEvent(item) && item.properties.$ai_is_error && (
            <LemonTag key="error-tag" type="danger">
                Error
            </LemonTag>
        ),
        latency >= 0.01 && (
            <LemonTag key="latency-tag" type="muted">
                {formatLLMLatency(latency)}
            </LemonTag>
        ),
        (usage != null || totalCost != null) && (
            <span key="usage-tag">
                {usage}
                {usage != null && totalCost != null && <span>{' / '}</span>}
                {totalCost != null && formatLLMCost(totalCost)}
            </span>
        ),
    ]
    const hasChildren = children.some((child) => !!child)

    return (
        <li key={item.id} className="mt-0.5" aria-current={isSelected}>
            <button
                type="button"
                onClick={() => onSelect(item.id)}
                className={classNames(
                    'w-full text-left flex flex-col gap-1 p-1 text-xs rounded min-h-8 justify-center hover:bg-accent-highlight-secondary cursor-pointer',
                    isSelected && 'bg-accent-highlight-secondary',
                    isCollapsedDueToFilter && 'min-h-4 min-w-0'
                )}
                data-attr="trace-event-link"
            >
                <div className="flex flex-row items-center gap-1.5">
                    <EventTypeTag event={item} size="small" />
                    {isBillable && (
                        <span title="Billable" aria-label="Billable" className="text-base">
                            💰
                        </span>
                    )}
                    {!isCollapsedDueToFilter && (
                        <Tooltip title={formatLLMEventTitle(item)}>
                            {searchQuery?.trim() ? (
                                <SearchHighlight
                                    string={formatLLMEventTitle(item)}
                                    substring={searchQuery}
                                    className="flex-1"
                                />
                            ) : (
                                <span className="flex-1 truncate">{formatLLMEventTitle(item)}</span>
                            )}
                        </Tooltip>
                    )}
                </div>
                {!isCollapsedDueToFilter && renderModelRow(item, searchQuery)}
                {!isCollapsedDueToFilter && hasChildren && (
                    <div className="flex flex-row flex-wrap text-secondary items-center gap-1.5">{children}</div>
                )}
            </button>
        </li>
    )
})

export function TreeNodeChildrenBase({
    tree,
    selectedEventId,
    onSelect,
    searchQuery,
    showBillingInfo,
    eventTypeExpanded,
}: TreeNodeChildrenBaseProps): JSX.Element {
    const [isCollapsed, setIsCollapsed] = useState(false)

    return (
        <NestingGroup isCollapsed={isCollapsed} onToggle={() => setIsCollapsed(!isCollapsed)}>
            {!isCollapsed ? (
                tree.map((node) => (
                    <React.Fragment key={node.event.id}>
                        <TreeNodeBase
                            node={node}
                            isSelected={!!selectedEventId && selectedEventId === node.event.id}
                            onSelect={onSelect}
                            searchQuery={searchQuery}
                            showBillingInfo={showBillingInfo}
                            eventTypeExpanded={eventTypeExpanded}
                        />
                        {node.children && (
                            <TreeNodeChildrenBase
                                tree={node.children}
                                selectedEventId={selectedEventId}
                                onSelect={onSelect}
                                searchQuery={searchQuery}
                                showBillingInfo={showBillingInfo}
                                eventTypeExpanded={eventTypeExpanded}
                            />
                        )}
                    </React.Fragment>
                ))
            ) : (
                <div
                    className="text-secondary hover:text-default text-xxs cursor-pointer p-1"
                    onClick={() => setIsCollapsed(false)}
                >
                    Show {pluralize(tree.length, 'collapsed child', 'collapsed children')}
                </div>
            )}
        </NestingGroup>
    )
}

export function TraceSidebarBase({
    trace,
    tree,
    selectedEventId,
    searchQuery,
    searchOccurrencesCount,
    onSearchChange,
    onSelectEvent,
    eventTypeExpanded,
    showBillingInfo,
    eventTypeFiltersSlot,
}: TraceSidebarBaseProps): JSX.Element {
    const ref = useRef<HTMLDivElement | null>(null)
    const [searchValue, setSearchValue] = useState(searchQuery)

    useEffect(() => {
        setSearchValue(searchQuery)
    }, [searchQuery])

    const debouncedSetSearchQuery = useDebouncedCallback((value: string) => {
        onSearchChange(value)
    }, 300)

    const handleSearchChange = (value: string): void => {
        setSearchValue(value)
        debouncedSetSearchQuery(value)
    }

    useEffect(() => {
        if (selectedEventId && ref.current) {
            const selectedNode = ref.current.querySelector(`[aria-current=true]`)

            if (selectedNode) {
                selectedNode.scrollIntoView({ block: 'center' })
            }
        }
    }, [selectedEventId])

    return (
        <aside
            className="sticky bottom-[var(--scene-padding)] border-primary max-h-fit bg-surface-primary border rounded overflow-hidden flex flex-col w-full md:w-80"
            ref={ref}
        >
            <h3 className="font-medium text-sm px-2 my-2">Tree</h3>
            <LemonDivider className="m-0" />
            <div className="p-2">
                <LemonInput
                    placeholder="Search trace..."
                    prefix={<IconSearch />}
                    value={searchValue}
                    onChange={handleSearchChange}
                    size="small"
                    data-attr="trace-search-input"
                />
                {searchValue.trim() && searchOccurrencesCount !== undefined && (
                    <div className="text-xs text-muted ml-1 mt-1">
                        {searchOccurrencesCount > 0 ? (
                            <>
                                {searchOccurrencesCount} {searchOccurrencesCount === 1 ? 'occurrence' : 'occurrences'}
                            </>
                        ) : (
                            'No occurrences'
                        )}
                    </div>
                )}
                {eventTypeFiltersSlot && <div className="mt-2">{eventTypeFiltersSlot}</div>}
            </div>
            <ul className="overflow-y-auto p-1 *:first:mt-0 overflow-x-hidden">
                <TreeNodeBase
                    node={{
                        event: trace,
                        displayTotalCost: trace.totalCost || 0,
                        displayLatency: trace.totalLatency || 0,
                        displayUsage: formatLLMUsage(trace),
                    }}
                    isSelected={!selectedEventId || selectedEventId === trace.id}
                    onSelect={onSelectEvent}
                    searchQuery={searchQuery}
                    showBillingInfo={showBillingInfo}
                    eventTypeExpanded={eventTypeExpanded}
                />
                <TreeNodeChildrenBase
                    tree={tree}
                    selectedEventId={selectedEventId}
                    onSelect={onSelectEvent}
                    searchQuery={searchQuery}
                    showBillingInfo={showBillingInfo}
                    eventTypeExpanded={eventTypeExpanded}
                />
            </ul>
        </aside>
    )
}
