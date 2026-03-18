import { useActions } from 'kea'
import posthog from 'posthog-js'

import { teamLogic } from 'scenes/teamLogic'

import { sidePanelSettingsLogic } from '~/layout/navigation-3000/sidepanel/panels/sidePanelSettingsLogic'
import { ProductIntentContext, ProductKey } from '~/queries/schema/schema-general'

export function useOpenLogsSettingsPanel(): () => void {
    const { addProductIntent } = useActions(teamLogic)
    const { openSettingsPanel } = useActions(sidePanelSettingsLogic)

    return () => {
        posthog.capture('logs settings opened')
        addProductIntent({
            product_type: ProductKey.LOGS,
            intent_context: ProductIntentContext.LOGS_SETTINGS_OPENED,
        })
        openSettingsPanel({
            sectionId: 'environment-logs',
            settingId: 'logs',
        })
    }
}
