import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import { Fragment, Suspense, useEffect, useRef } from 'react'

import { Button } from '@posthog/quill'
import { PostHogErrorBoundary } from '@posthog/react'

import { lazyWithRetry } from 'lib/utils/retryImport'
import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'

import { SidebarRow } from '~/layout/today/sidebar/SidebarRow'
import { SidebarSearchList } from '~/layout/today/sidebar/SidebarSearchList'
import { SortableSidebarList } from '~/layout/today/sidebar/SortableSidebarList'

import type {
    AnalyticsFragmentButtonApi,
    AnalyticsFragmentLinkApi,
    AnalyticsFragmentSectionApi,
    AnalyticsListSourceApi,
    AnalyticsFragmentMetricApi,
} from './generated/api.schemas'
import { SidebarButton } from './SidebarButton'
import { sidebarConfiguration, SidebarContextConfiguration } from './sidebarContexts'
import { SidebarCustomizationControls } from './SidebarCustomizationControls'
import { sidebarCustomizationLogic } from './sidebarCustomizationLogic'
import { SIDEBAR_ICONS } from './sidebarIcons'
import { SidebarLayoutSections } from './SidebarLayoutSections'

const SidebarAgentListener = lazyWithRetry(() =>
    import('./SidebarAgentListener').then((m) => ({ default: m.SidebarAgentListener }))
)

export interface SidebarNavigationItem {
    value: string
    label: string
    icon?: JSX.Element | null
    to: string
    active: boolean
    action?: JSX.Element
    dataAttr?: string
    onClick?: () => void
    wrap?: (row: JSX.Element) => JSX.Element
    /** Sent with `sidebar item opened`. A row without them, such as a hint, reports no open. */
    eventProperties?: Record<string, string>
}

const SEARCH_SETTLE_MS = 800

export interface CustomizedSidebarProps {
    configuration: SidebarContextConfiguration
    search: { query: string; onChange: (query: string) => void; label: string; empty: string }
    sections: { isOpen: (id: string) => boolean; toggle: (id: string) => void; dataAttrPrefix: string }
    navigation: {
        resolve: (
            item: AnalyticsFragmentLinkApi | AnalyticsFragmentButtonApi
        ) => Omit<SidebarNavigationItem, 'value'> | null
        lists: Partial<Record<AnalyticsListSourceApi, SidebarNavigationItem[]>>
        /** Lists whose rows can be dragged into a new order. Indexes refer to the list as given. */
        reorder?: Partial<Record<AnalyticsListSourceApi, (fromIndex: number, toIndex: number) => void>>
        metric: (item: AnalyticsFragmentMetricApi, value: string) => JSX.Element
    }
    customization: { prompt: string; event: string }
    dataAttrPrefix: string
    refreshError: string
}

export function CustomizedSidebar(props: CustomizedSidebarProps): JSX.Element {
    const { currentProjectId } = useValues(teamLogic)
    const { user } = useValues(userLogic)
    const identity = {
        configuration: sidebarConfiguration(props.configuration),
        projectId: String(currentProjectId),
        userId: user?.uuid ?? '',
    }
    const logic = sidebarCustomizationLogic(identity)
    const { sidebarLayout, sidebarCustomizationEnabled, sidebarFailed, sidebarLoading, sidebarCustomized } =
        useValues(logic)
    const { loadSidebar } = useActions(logic)
    const query = props.search.query.trim()
    const matches = (label: string): boolean => label.toLowerCase().includes(query.toLowerCase())
    // `customized` lets an analysis drop personalized layouts, whose section ids are the person's own.
    const reportOpened = (item: SidebarNavigationItem, section: string, source: string): void => {
        // pinned: analytics event name and properties. Renaming them breaks dashboards.
        posthog.capture('sidebar item opened', {
            ...item.eventProperties,
            sidebar: props.configuration.context,
            section,
            source,
            from_search: query !== '',
            customized: sidebarCustomized,
        })
    }
    const renderRow = (item: SidebarNavigationItem, section: string, source: string): JSX.Element => {
        const onClick = (): void => {
            item.onClick?.()
            if (item.eventProperties) {
                reportOpened(item, section, source)
            }
        }
        const row = <SidebarRow {...item} onClick={onClick} />
        return <Fragment key={item.value}>{item.wrap ? item.wrap(row) : row}</Fragment>
    }
    const renderList = (section: string, source: AnalyticsListSourceApi, key: string): JSX.Element[] => {
        const rows = props.navigation.lists[source] ?? []
        const renderListRow = (row: SidebarNavigationItem): JSX.Element => renderRow(row, section, source)
        const onReorder = props.navigation.reorder?.[source]
        // A filtered list hides rows, so a drop there has no clear place in the full order.
        if (onReorder && rows.length > 1 && !query) {
            return [<SortableSidebarList key={key} rows={rows} renderRow={renderListRow} onReorder={onReorder} />]
        }
        return rows.filter((row) => matches(row.label)).map(renderListRow)
    }
    const renderItem = (
        section: AnalyticsFragmentSectionApi,
        item: AnalyticsFragmentSectionApi['items'][number],
        index: number
    ): JSX.Element[] => {
        const value = `${section.id}:${index}`
        if (item.type === 'list') {
            return renderList(section.id, item.source, value)
        }
        if (item.type === 'metric') {
            return matches(item.label) ? [<Fragment key={value}>{props.navigation.metric(item, value)}</Fragment>] : []
        }
        if (item.type !== 'link' && item.type !== 'button') {
            return []
        }
        const target = props.navigation.resolve(item)
        if (!target || !matches(target.label)) {
            return []
        }
        if (item.type === 'button') {
            return [
                <SidebarButton
                    key={value}
                    value={value}
                    target={item}
                    resolved={target}
                    dataAttr={`${props.dataAttrPrefix}-${section.id}-button`}
                />,
            ]
        }
        const eventProperties: Record<string, string> =
            item.to.kind === 'page' ? { page: item.to.page } : { object_type: item.to.kind }
        return [
            renderRow(
                { ...target, value, dataAttr: `${props.dataAttrPrefix}-${section.id}`, eventProperties },
                section.id,
                'link'
            ),
        ]
    }

    const resultCount = query
        ? sidebarLayout.sections.reduce(
              (total, section) =>
                  total + section.items.flatMap((item, index) => renderItem(section, item, index)).length,
              0
          )
        : 0
    // Read when the search settles rather than when it starts, because rows that load during the wait change it.
    const latestResultCount = useRef(resultCount)
    latestResultCount.current = resultCount
    // Reports the search the person stops on, once per query. A count that changes later, for example when an opened
    // row joins Recents, is not a new search. The text stays out of the event because it can hold the name of an item.
    useEffect(() => {
        if (!query) {
            return
        }
        const timeout = window.setTimeout(() => {
            // pinned: analytics event name and properties. Renaming them breaks dashboards.
            posthog.capture('sidebar search used', {
                sidebar: props.configuration.context,
                query_length: query.length,
                result_count: latestResultCount.current,
                zero_results: latestResultCount.current === 0,
                customized: sidebarCustomized,
            })
        }, SEARCH_SETTLE_MS)
        return () => window.clearTimeout(timeout)
        // Only a new query restarts the wait. The other values are read when the timer fires.
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [query])
    return (
        <div className="TodayPane group/colorful-product-icons colorful-product-icons-true" data-quill>
            <SidebarSearchList
                query={props.search.query}
                onQueryChange={props.search.onChange}
                searchLabel={props.search.label}
                dataAttr={`${props.dataAttrPrefix}-search`}
            >
                <SidebarLayoutSections
                    sections={sidebarLayout.sections}
                    renderIcon={(icon) => SIDEBAR_ICONS[icon] ?? null}
                    isSectionOpen={props.sections.isOpen}
                    toggleSection={props.sections.toggle}
                    dataAttrPrefix={props.sections.dataAttrPrefix}
                    empty={
                        props.search.query.trim() ? (
                            <div className="px-2 py-1 text-sm text-muted-foreground">{props.search.empty}</div>
                        ) : null
                    }
                    renderItem={renderItem}
                />
            </SidebarSearchList>
            {sidebarCustomizationEnabled && sidebarFailed && (
                <div className="flex items-center gap-2 px-2 py-1 text-xs text-muted-foreground">
                    <span>{props.refreshError}</span>
                    <Button
                        size="sm"
                        variant="outline"
                        loading={sidebarLoading}
                        onClick={loadSidebar}
                        data-attr={`${props.dataAttrPrefix}-retry`}
                    >
                        Try again
                    </Button>
                </div>
            )}
            {sidebarCustomizationEnabled && (
                <>
                    <SidebarCustomizationControls
                        {...props}
                        {...identity}
                        customizePrompt={props.customization.prompt}
                        customizeEvent={props.customization.event}
                    />
                    <PostHogErrorBoundary fallback={<></>}>
                        <Suspense fallback={null}>
                            <SidebarAgentListener {...identity} />
                        </Suspense>
                    </PostHogErrorBoundary>
                </>
            )}
        </div>
    )
}
