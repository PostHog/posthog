import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useMemo } from 'react'

import { IconPlus } from '@posthog/icons'

import { removeProjectIdIfPresent } from 'lib/utils/kea-router'
import { analyticsListFiltersFromUrl } from 'scenes/analytics/analyticsListLogic'
import { AnalyticsPinButton } from 'scenes/analytics/AnalyticsPinButton'
import { analyticsPinnedLogic } from 'scenes/analytics/analyticsPinnedLogic'
import { AnalyticsSpaceGlyph } from 'scenes/analytics/AnalyticsSpaceGlyph'
import { AnalyticsTypeIcon } from 'scenes/analytics/AnalyticsTypeIcon'
import { ANALYTICS_TYPE_INFO, AnalyticsType } from 'scenes/analytics/analyticsUtils'
import { urls } from 'scenes/urls'

import { iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'
import { productPreview } from '~/layout/today/todayPreviewCards'
import { TodayPreviewTrigger } from '~/layout/today/TodayPreviewTrigger'
import { FileSystemIconType } from '~/queries/schema/schema-general'
import { InsightShortId } from '~/types'

import { CustomizedSidebar, SidebarNavigationItem } from 'products/ui_customization/frontend/CustomizedSidebar'
import type { AnalyticsListSourceApi } from 'products/ui_customization/frontend/generated/api.schemas'

import { ANALYTICS_SIDEBAR_CONFIGURATION } from './analyticsSidebarConfiguration'
import { todayAnalyticsLogic } from './todayAnalyticsLogic'
import { TodayAnalyticsMetric } from './TodayAnalyticsMetric'
import { resolveSidebarTarget } from './todayAnalyticsSidebarTargets'

function AnalyticsItemIcon({ type }: { type: AnalyticsType }): JSX.Element {
    return (
        // eslint-disable-next-line react/forbid-dom-props
        <span style={{ color: ANALYTICS_TYPE_INFO[type].color }}>
            <AnalyticsTypeIcon type={type} />
        </span>
    )
}

/**
 * The Analytics sub-nav, drawn from the person's layout: sections of links, buttons, metrics and the lists PostHog
 * fills. The default layout is one more layout, so it draws the same way.
 */
export function TodayAnalyticsSidebar(): JSX.Element {
    const { fromPostHog, recentAnalytics, searchQuery, isSectionOpen } = useValues(todayAnalyticsLogic)
    const { toggleSection, setSearchQuery } = useActions(todayAnalyticsLogic)
    const { pinnedAnalytics, shortcutDataLoading, hasAnalyticsItems } = useValues(analyticsPinnedLogic)
    const { movePinned, showPinHint } = useActions(analyticsPinnedLogic)
    const { location, searchParams } = useValues(router)
    const path = removeProjectIdIfPresent(location.pathname)
    const listFilters =
        path === urls.analyticsList() || path === urls.analyticsMine()
            ? analyticsListFiltersFromUrl(searchParams)
            : null
    const openFolder = path === urls.analyticsList() ? (listFilters?.folder ?? null) : null
    const fromPostHogPreviews = useMemo(
        () => new Map(fromPostHog.map((product) => [product.key, productPreview(product.label, product.item)])),
        [fromPostHog]
    )

    const isOpen = (targetPath: string): boolean =>
        path === removeProjectIdIfPresent(targetPath) && (targetPath !== urls.analyticsList() || openFolder === null)

    const lists: Record<AnalyticsListSourceApi, SidebarNavigationItem[]> = {
        pinned: pinnedAnalytics.map((pinned) =>
            pinned.kind === 'collection'
                ? {
                      value: `pinned:${pinned.key}`,
                      label: pinned.name,
                      icon: <AnalyticsSpaceGlyph name={pinned.name} />,
                      to: urls.analyticsList({ folder: pinned.path }),
                      active: openFolder === pinned.path,
                      action: (
                          <AnalyticsPinButton
                              target={{ type: 'folder', ref: pinned.path, name: pinned.name }}
                              dataAttr="analytics-sidebar-unpin-space"
                          />
                      ),
                      dataAttr: 'analytics-sidebar-starred-space',
                  }
                : {
                      value: `pinned:${pinned.key}`,
                      label: pinned.item.name,
                      icon: <AnalyticsItemIcon type={pinned.item.type} />,
                      to: pinned.item.href,
                      active: path === removeProjectIdIfPresent(pinned.item.href),
                      action: (
                          <AnalyticsPinButton
                              target={{
                                  type: pinned.item.type,
                                  ref: pinned.item.id,
                                  name: pinned.item.name,
                                  href: pinned.item.href,
                              }}
                              dataAttr="analytics-sidebar-unpin"
                          />
                      ),
                      dataAttr: 'analytics-sidebar-pinned',
                  }
        ),
        recents: recentAnalytics.map((item) => ({
            value: `recent:${item.type}:${item.id}`,
            label: item.name,
            icon: <AnalyticsItemIcon type={item.type} />,
            to: item.href,
            active: path === removeProjectIdIfPresent(item.href),
            action: (
                <AnalyticsPinButton
                    target={{ type: item.type, ref: item.id, name: item.name, href: item.href }}
                    dataAttr="analytics-sidebar-recent-pin"
                />
            ),
            dataAttr: 'analytics-sidebar-recent',
        })),
        by_posthog: fromPostHog.map((product) => {
            const productPath = product.href.split(/[?#]/)[0]
            const preview = fromPostHogPreviews.get(product.key)
            return {
                value: `by-posthog:${product.key}`,
                label: product.label,
                icon: iconForType(
                    (product.item.iconType ?? product.item.type) as FileSystemIconType,
                    product.item.iconColor
                ),
                to: product.href,
                active: path === productPath || path.startsWith(`${productPath}/`),
                dataAttr: 'analytics-sidebar-by-posthog',
                wrap: preview?.description
                    ? (row) => <TodayPreviewTrigger payload={preview}>{row}</TodayPreviewTrigger>
                    : undefined,
            }
        }),
    }

    // With nothing pinned, the section stays to show that pinning exists. A search hides it, as it matches nothing.
    if (lists.pinned.length === 0 && !shortcutDataLoading && hasAnalyticsItems && !searchQuery.trim()) {
        lists.pinned = [
            {
                value: 'pinned:add',
                label: 'Add a pinned item',
                icon: <IconPlus />,
                to: urls.analyticsList(),
                active: false,
                onClick: showPinHint,
                dataAttr: 'analytics-sidebar-pinned-add',
            },
        ]
    }

    return (
        <CustomizedSidebar
            configuration={ANALYTICS_SIDEBAR_CONFIGURATION}
            search={{
                query: searchQuery,
                onChange: setSearchQuery,
                label: 'Search analytics',
                empty: 'Nothing in Analytics matches your search.',
            }}
            sections={{ isOpen: isSectionOpen, toggle: toggleSection, dataAttrPrefix: 'analytics-section' }}
            navigation={{
                lists,
                reorder: {
                    pinned: (fromIndex, toIndex) =>
                        movePinned(pinnedAnalytics[fromIndex].shortcutId, pinnedAnalytics[toIndex].shortcutId),
                },
                resolve: (item) => {
                    const target = resolveSidebarTarget(item.to, item.label, item.icon)
                    return target
                        ? {
                              ...target,
                              active: isOpen(target.path),
                              wrap: target.explainer
                                  ? (row) => (
                                        <TodayPreviewTrigger payload={target.explainer!}>{row}</TodayPreviewTrigger>
                                    )
                                  : undefined,
                          }
                        : null
                },
                metric: (item, value) => (
                    <TodayAnalyticsMetric
                        item={item}
                        value={value}
                        active={isOpen(urls.insightView(item.insight as InsightShortId))}
                    />
                ),
            }}
            customization={{
                prompt:
                    'Help me personalize my Analytics sidebar for my current work. Start by checking what is already there. ' +
                    'If I give a specific change, apply it directly and ask only for missing details. Otherwise, ask what ' +
                    'I need to open most often and which existing sections I want to keep. For a general redesign, use ' +
                    'my recent activity summary when available, together with Pinned and Recents, to suggest a few useful ' +
                    'destinations and briefly explain why. My stated goal takes priority over inferred interests. If ' +
                    'recent activity is unavailable, ask what matters now. Prefer removing, reordering, ' +
                    'and reusing existing links. Do not offer a checklist of things to add or add shortcuts that duplicate ' +
                    'Pinned, Recents, or By PostHog. Only add live metrics if I ask for them. Keep the menu compact and ' +
                    'use the supported navigation controls. After saving, briefly explain what changed and how to undo it.',
                event: 'analytics sidebar customize clicked',
            }}
            dataAttrPrefix="analytics-sidebar"
            refreshError="Couldn’t refresh the Analytics sidebar."
        />
    )
}
