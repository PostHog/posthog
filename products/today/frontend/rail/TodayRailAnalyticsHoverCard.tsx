import { useValues } from 'kea'

import { pinnedAnalyticsFromShortcuts } from 'scenes/analytics/analyticsPinnedLogic'
import { AnalyticsSpaceGlyph } from 'scenes/analytics/AnalyticsSpaceGlyph'
import { urls } from 'scenes/urls'

import { sidebarPinsLogic } from '~/layout/today/sidebar/sidebarPinsLogic'
import { recentItemsModel } from '~/models/recentItemsModel'

import { AnalyticsItemIcon } from '../analytics/AnalyticsItemIcon'
import { todayAnalyticsLogic } from '../analytics/todayAnalyticsLogic'
import { TodayRailPreviewList } from './TodayRailPreviewList'

export function TodayRailAnalyticsHoverCard({ onAction }: { onAction: () => void }): JSX.Element {
    const { recentAnalytics } = useValues(todayAnalyticsLogic)
    const { shortcutData, shortcutDataLoading } = useValues(sidebarPinsLogic)
    const pinnedAnalytics = pinnedAnalyticsFromShortcuts(shortcutData)
    const { recentsLoading } = useValues(recentItemsModel)

    return (
        <TodayRailPreviewList
            title="Analytics"
            pins={pinnedAnalytics.map((pin) =>
                pin.kind === 'collection'
                    ? {
                          name: pin.name,
                          href: urls.analyticsList({ folder: pin.path }),
                          icon: <AnalyticsSpaceGlyph name={pin.name} />,
                      }
                    : {
                          name: pin.item.name,
                          href: pin.item.href,
                          icon: <AnalyticsItemIcon type={pin.item.type} />,
                      }
            )}
            recents={recentAnalytics.map((item) => ({
                name: item.name,
                href: item.href,
                icon: <AnalyticsItemIcon type={item.type} />,
            }))}
            loading={shortcutDataLoading || recentsLoading}
            onAction={onAction}
        />
    )
}
