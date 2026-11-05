import type { ReactElement } from 'react'
import { TabScene } from '@/features/tabs/TabScene'

import { ViewsScreen } from '@/features/views/list/ViewsScreen'

export default function ViewsRoute(): ReactElement {
    return (
        <TabScene tab="views">
            <ViewsScreen />
        </TabScene>
    )
}
