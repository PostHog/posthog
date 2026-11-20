import { AnalyticsTypeIcon } from 'scenes/analytics/AnalyticsTypeIcon'
import { ANALYTICS_TYPE_INFO, AnalyticsType } from 'scenes/analytics/analyticsUtils'

export function AnalyticsItemIcon({ type }: { type: AnalyticsType }): JSX.Element {
    return (
        // eslint-disable-next-line react/forbid-dom-props
        <span style={{ color: ANALYTICS_TYPE_INFO[type].color }}>
            <AnalyticsTypeIcon type={type} />
        </span>
    )
}
