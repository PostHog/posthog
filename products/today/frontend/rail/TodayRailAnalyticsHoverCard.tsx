import { useValues } from 'kea'

import { analyticsPinnedLogic } from 'scenes/analytics/analyticsPinnedLogic'
import { AnalyticsSpaceGlyph } from 'scenes/analytics/AnalyticsSpaceGlyph'
import { AnalyticsTypeIcon } from 'scenes/analytics/AnalyticsTypeIcon'
import { urls } from 'scenes/urls'

import { sidebarPinsLogic } from '~/layout/today/sidebar/sidebarPinsLogic'
import { recentItemsModel } from '~/models/recentItemsModel'

import { todayAnalyticsLogic } from '../analytics/todayAnalyticsLogic'
import { TodayRailPreviewList } from './TodayRailPreviewList'

export function TodayRailAnalyticsHoverCard({ onAction }: { onAction: () => void }): JSX.Element {
    const { pinnedAnalytics } = useValues(analyticsPinnedLogic)
    const { recentAnalytics } = useValues(todayAnalyticsLogic)
    const { shortcutDataLoading } = useValues(sidebarPinsLogic)
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
                          icon: <AnalyticsTypeIcon type={pin.item.type} />,
                      }
            )}
            recents={recentAnalytics.map((item) => ({
                name: item.name,
                href: item.href,
                icon: <AnalyticsTypeIcon type={item.type} />,
            }))}
            loading={shortcutDataLoading || recentsLoading}
            onAction={onAction}
        />
    )
}
