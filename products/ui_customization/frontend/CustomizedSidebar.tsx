import { useActions, useValues } from 'kea'
import { Fragment, Suspense } from 'react'

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
    wrap?: (row: JSX.Element) => JSX.Element
}

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
    const { sidebarLayout, sidebarCustomizationEnabled, sidebarFailed, sidebarLoading } = useValues(logic)
    const { loadSidebar, searchTyped, itemOpened } = useActions(logic)
    const renderRow = (item: SidebarNavigationItem, onClick: () => void): JSX.Element => {
        const row = <SidebarRow {...item} onClick={onClick} />
        return <Fragment key={item.value}>{item.wrap ? item.wrap(row) : row}</Fragment>
    }
    const rowsFor = (
        query: string,
        section: AnalyticsFragmentSectionApi,
        item: AnalyticsFragmentSectionApi['items'][number],
        index: number
    ): JSX.Element[] => {
        const matches = (label: string): boolean => label.toLowerCase().includes(query.trim().toLowerCase())
        const fromSearch = query.trim() !== ''
        const value = `${section.id}:${index}`
        if (item.type === 'list') {
            const rows = props.navigation.lists[item.source] ?? []
            const onReorder = props.navigation.reorder?.[item.source]
            const opened = (position: number): void => itemOpened(section.id, item.source, position, fromSearch)
            // A filtered list hides rows, so a drop there has no clear place in the full order.
            if (onReorder && rows.length > 1 && !fromSearch) {
                return [
                    <SortableSidebarList
                        key={value}
                        rows={rows}
                        renderRow={(row) => renderRow(row, () => opened(rows.indexOf(row)))}
                        onReorder={onReorder}
                    />,
                ]
            }
            return rows
                .filter((row) => matches(row.label))
                .map((row, position) => renderRow(row, () => opened(position)))
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
        return [
            renderRow({ ...target, value, dataAttr: `${props.dataAttrPrefix}-${section.id}` }, () =>
                itemOpened(section.id, 'link', undefined, fromSearch)
            ),
        ]
    }
    const resultCountFor = (query: string): number =>
        sidebarLayout.sections.reduce(
            (total, section) =>
                total +
                section.items.reduce((count, item, index) => count + rowsFor(query, section, item, index).length, 0),
            0
        )
    return (
        <div className="TodayPane group/colorful-product-icons colorful-product-icons-true" data-quill>
            <SidebarSearchList
                query={props.search.query}
                onQueryChange={(query) => {
                    props.search.onChange(query)
                    searchTyped(query.trim().length, resultCountFor(query))
                }}
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
                    renderItem={(section, item, index) => rowsFor(props.search.query, section, item, index)}
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
