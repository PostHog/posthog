import { BindLogic, useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { LemonButton } from '@posthog/lemon-ui'

import { EmptyMessage } from 'lib/components/EmptyMessage/EmptyMessage'
import { IconOpenInNew } from 'lib/lemon-ui/icons'
import { sceneLogic } from 'scenes/sceneLogic'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import {
    MaxErrorTrackingIssuePreview,
    MaxErrorTrackingSearchResponse,
} from '~/queries/schema/schema-assistant-error-tracking'

import { issueFiltersLogic } from 'products/error_tracking/frontend/components/IssueFilters/issueFiltersLogic'
import {
    ErrorTrackingQueryOrderBy,
    ErrorTrackingQueryOrderDirection,
    ErrorTrackingQueryStatus,
    issueQueryOptionsLogic,
} from 'products/error_tracking/frontend/components/IssueQueryOptions/issueQueryOptionsLogic'
import { ERROR_TRACKING_SCENE_LOGIC_KEY } from 'products/error_tracking/frontend/scenes/ErrorTrackingScene/errorTrackingSceneLogic'

import { MessageTemplate } from '../../../messages/MessageTemplate'
import { ErrorTrackingFiltersSummary } from './ErrorTrackingFiltersSummary'
import { ErrorTrackingIssueCard } from './ErrorTrackingIssueCard'
import { MaxErrorTrackingWidgetLogicProps, maxErrorTrackingWidgetLogic } from './maxErrorTrackingWidgetLogic'

export function ErrorTrackingFiltersWidget({
    toolCallId,
    filters,
    embedded = false,
}: {
    toolCallId: string
    filters: MaxErrorTrackingSearchResponse | null | undefined
    embedded?: boolean
}): JSX.Element {
    const logicProps: MaxErrorTrackingWidgetLogicProps = { toolCallId, filters }

    if (!filters) {
        const emptyState = (
            <div className="py-2">
                <EmptyMessage
                    title="Error tracking data unavailable"
                    description="The error tracking search could not be completed"
                />
            </div>
        )
        if (embedded) {
            return <div className="overflow-hidden rounded border bg-surface-primary">{emptyState}</div>
        }
        return (
            <MessageTemplate type="ai" wrapperClassName="w-full" boxClassName="p-0 overflow-hidden">
                {emptyState}
            </MessageTemplate>
        )
    }

    return (
        <BindLogic logic={maxErrorTrackingWidgetLogic} props={logicProps}>
            <ErrorTrackingFiltersWidgetContent filters={filters} embedded={embedded} />
        </BindLogic>
    )
}

function ErrorTrackingFiltersWidgetContent({
    filters,
    embedded,
}: {
    filters: MaxErrorTrackingSearchResponse
    embedded: boolean
}): JSX.Element {
    const { activeSceneId } = useValues(sceneLogic)
    const isOnErrorTrackingPage = activeSceneId === Scene.ErrorTracking

    const { issues, hasMore, isLoading } = useValues(maxErrorTrackingWidgetLogic)
    const { loadMoreIssues } = useActions(maxErrorTrackingWidgetLogic)

    const filtersLogic = issueFiltersLogic({ logicKey: ERROR_TRACKING_SCENE_LOGIC_KEY })
    const queryOptionsLogic = issueQueryOptionsLogic({ logicKey: ERROR_TRACKING_SCENE_LOGIC_KEY })

    const { setDateRange, setSearchQuery } = useActions(filtersLogic)
    const { setStatus, setOrderBy, setOrderDirection } = useActions(queryOptionsLogic)

    // Automatically apply filters when on the Error Tracking page
    useEffect(() => {
        if (isOnErrorTrackingPage) {
            if (filters.date_from || filters.date_to) {
                setDateRange({ date_from: filters.date_from ?? null, date_to: filters.date_to ?? null })
            }
            if (filters.search_query) {
                setSearchQuery(filters.search_query)
            }
            if (filters.status) {
                setStatus(filters.status as ErrorTrackingQueryStatus)
            }
            if (filters.order_by) {
                setOrderBy(filters.order_by as ErrorTrackingQueryOrderBy)
            }
            if (filters.order_direction) {
                setOrderDirection(filters.order_direction as ErrorTrackingQueryOrderDirection)
            }
        }
    }, [
        isOnErrorTrackingPage,
        setOrderDirection,
        filters.search_query,
        filters.order_direction,
        setOrderBy,
        filters.date_from,
        filters.order_by,
        filters.status,
        setSearchQuery,
        setStatus,
        filters.date_to,
        setDateRange,
    ])

    const buildErrorTrackingUrl = (): string => {
        const params = new URLSearchParams()
        if (filters.status) {
            params.set('status', filters.status)
        }
        if (filters.search_query) {
            params.set('searchQuery', filters.search_query)
        }
        if (filters.date_from) {
            params.set('dateFrom', filters.date_from)
        }
        if (filters.date_to) {
            params.set('dateTo', filters.date_to)
        }
        const query = params.toString()
        return urls.errorTracking() + (query ? `?${query}` : '')
    }

    const hasIssues = issues.length > 0
    const errorTrackingUrl = buildErrorTrackingUrl()

    const content = (
        <>
            {!isOnErrorTrackingPage && (
                <div className="flex items-center justify-between px-2 pt-2">
                    <span className="text-xs font-semibold text-secondary">Error tracking</span>
                    <LemonButton
                        to={errorTrackingUrl}
                        icon={<IconOpenInNew />}
                        size="xsmall"
                        tooltip="Open in Error tracking"
                    />
                </div>
            )}
            <ErrorTrackingFiltersSummary filters={filters} />
            <div className="border-t">
                {hasIssues ? (
                    <div className="*:not-first:border-t max-h-80 overflow-y-auto">
                        {issues.map((issue: MaxErrorTrackingIssuePreview) => (
                            <ErrorTrackingIssueCard key={issue.id} issue={issue} />
                        ))}
                    </div>
                ) : (
                    <div className="py-2">
                        <EmptyMessage title="No issues found" description="No issues match the specified filters" />
                    </div>
                )}
                {hasMore && (
                    <div className="flex justify-center p-2 border-t">
                        <LemonButton type="tertiary" size="xsmall" onClick={() => loadMoreIssues()} loading={isLoading}>
                            Load more issues
                        </LemonButton>
                    </div>
                )}
            </div>
        </>
    )

    if (embedded) {
        return <div className="overflow-hidden rounded border bg-surface-primary">{content}</div>
    }

    return (
        <MessageTemplate type="ai" wrapperClassName="w-full" boxClassName="p-0 overflow-hidden">
            {content}
        </MessageTemplate>
    )
}
