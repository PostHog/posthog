import { useActions } from 'kea'

import { useToolStreamListener } from 'products/posthog_ai/frontend/api/logics'

import { SidebarCustomizationProps, sidebarCustomizationLogic } from './sidebarCustomizationLogic'

/** Reloads the Analytics sidebar when PostHog AI changes it, so the new layout shows as soon as the agent saves it. */
export function SidebarAgentListener(props: SidebarCustomizationProps): null {
    const { loadSidebar } = useActions(sidebarCustomizationLogic(props))
    useToolStreamListener({
        tools: ['ui-customization-analytics-sidebar-update', 'ui-customization-analytics-sidebar-reset'],
        onEvent: (event) => {
            if (event.phase === 'completed') {
                loadSidebar()
            }
        },
    })
    return null
}
