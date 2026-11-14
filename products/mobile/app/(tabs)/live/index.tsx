import type { ReactElement } from 'react'
import { LiveScreen } from '@/features/live/LiveScreen'
import { TabScene } from '@/features/tabs/TabScene'

export default function LiveTabRoute(): ReactElement {
    return (
        <TabScene tab="live">
            <LiveScreen from="tab" chrome="tab" />
        </TabScene>
    )
}
