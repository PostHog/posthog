import { useActions } from 'kea'
import { router } from 'kea-router'
import posthog from 'posthog-js'

import { ProductIntentContext, ProductKey } from '@posthog/query-frontend/schema/schema-general'

import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

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
