import { useActions, useValues } from 'kea'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { SceneExport } from 'scenes/sceneTypes'

import { MessagingTab, messagingTabsLogic } from './messagingTabsLogic'

export function MessagingTabs(): JSX.Element {
    const { currentTab } = useValues(messagingTabsLogic)
    const { setTab } = useActions(messagingTabsLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    const isLibraryEnabled = featureFlags[FEATURE_FLAGS.MESSAGING_LIBRARY]
    const isAutomationEnabled = featureFlags[FEATURE_FLAGS.MESSAGING_AUTOMATION]
    const isProviderEnabled = featureFlags[FEATURE_FLAGS.MESSAGING_PROVIDER]

    const tabs = [{ key: 'broadcasts', label: 'Broadcasts' }]

    if (isLibraryEnabled) {
        tabs.push({ key: 'library', label: 'Library' })
    }

    if (isAutomationEnabled) {
        tabs.push({ key: 'automations', label: 'Automations' })
    }

    if (isProviderEnabled) {
        tabs.push({ key: 'providers', label: 'Providers' })
    }

    return <LemonTabs activeKey={currentTab} onChange={(tab) => setTab(tab as MessagingTab)} tabs={tabs} />
}

export const scene: SceneExport = {
    component: MessagingTabs,
    logic: messagingTabsLogic,
}
