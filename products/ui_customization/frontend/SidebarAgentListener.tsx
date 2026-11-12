import { useActions } from 'kea'

import { useToolStreamListener } from 'products/posthog_ai/frontend/api/logics'

import { CUSTOMIZATION_WRITE_TOOLS, customizationWasChanged } from './customizationToolEvents'
import { SidebarCustomizationProps, sidebarCustomizationLogic } from './sidebarCustomizationLogic'

/** Reloads the selected sidebar when PostHog AI changes its context, so the new layout shows as soon as the agent saves it. */
export function SidebarAgentListener(props: SidebarCustomizationProps): null {
    const { loadSidebar } = useActions(sidebarCustomizationLogic(props))
    useToolStreamListener({
        tools: CUSTOMIZATION_WRITE_TOOLS,
        onEvent: (event) => {
            if (customizationWasChanged(event, props.configuration.context)) {
                loadSidebar()
            }
        },
    })
    return null
}
