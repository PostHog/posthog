import type { ReactElement } from 'react'
import { TabScene } from '@/features/tabs/TabScene'
import { WebAnalyticsScreen } from '@/features/views/webAnalytics/WebAnalyticsScreen'

export default function WebAnalyticsTabRoute(): ReactElement {
    return (
        <TabScene tab="web_analytics">
            <WebAnalyticsScreen from="tab" chrome="tab" />
        </TabScene>
    )
}
