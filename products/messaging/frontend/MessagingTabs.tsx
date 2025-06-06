import { useActions, useValues } from 'kea'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { SceneExport } from 'scenes/sceneTypes'

import { MessagingTab, messagingTabsLogic } from './messagingTabsLogic'

export function MessagingTabs(): JSX.Element {
    const { currentTab } = useValues(messagingTabsLogic)
    const { setTab } = useActions(messagingTabsLogic)

    const tabs = [
        { key: 'broadcasts', label: 'Broadcasts' },
        { key: 'campaigns', label: 'Campaigns' },
        { key: 'library', label: 'Templates' },
        { key: 'senders', label: 'Senders' },
    ]

    return <LemonTabs activeKey={currentTab} onChange={(tab) => setTab(tab as MessagingTab)} tabs={tabs} />
}

export const scene: SceneExport = {
    component: MessagingTabs,
    logic: messagingTabsLogic,
}
