import { useActions } from 'kea'
import { router } from 'kea-router'
import posthog from 'posthog-js'

import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { ProductIntentContext, ProductKey } from '~/queries/schema/schema-general'

export function useOpenLogsSettingsPanel(): () => void {
    const { addProductIntent } = useActions(teamLogic)

    return () => {
        posthog.capture('logs settings opened')
        addProductIntent({
            product_type: ProductKey.LOGS,
            intent_context: ProductIntentContext.LOGS_SETTINGS_OPENED,
        })
        router.actions.push(urls.settings('environment-logs', 'logs'))
    }
}
