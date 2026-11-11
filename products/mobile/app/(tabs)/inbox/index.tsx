import type { ReactElement } from 'react'
import { InboxScreen } from '@/features/inbox/InboxScreen'
import { TabScene } from '@/features/tabs/TabScene'

export default function InboxRoute(): ReactElement {
    return (
        <TabScene tab="inbox">
            <InboxScreen />
        </TabScene>
    )
}
