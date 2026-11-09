import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { mcpAnalyticsOnboardingLogic } from './mcpAnalyticsOnboardingLogic'
import { mcpSetupModeLogic } from './setupMode/mcpSetupModeLogic'

/** Records that the viewer was on the page when their first tool call landed. */
export function FirstDataSeen(): null {
    const { firstDataWatch } = useValues(mcpAnalyticsOnboardingLogic)
    const { acknowledgeFirstData } = useActions(mcpAnalyticsOnboardingLogic)

    useEffect(() => {
        if (firstDataWatch === 'arrived') {
            // Looked up rather than connected: with the setup mode flag off, its logic never mounts.
            acknowledgeFirstData(mcpSetupModeLogic.findMounted()?.values.isOpen ? 'setup_mode' : 'dashboard')
        }
    }, [firstDataWatch, acknowledgeFirstData])

    return null
}
