import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { useHogfetti } from 'lib/components/Hogfetti/Hogfetti'

import { mcpAnalyticsOnboardingLogic } from './mcpAnalyticsOnboardingLogic'

export function FirstDataCelebration(): JSX.Element {
    const { firstDataWatch } = useValues(mcpAnalyticsOnboardingLogic)
    const { acknowledgeFirstData } = useActions(mcpAnalyticsOnboardingLogic)
    const { trigger, HogfettiComponent } = useHogfetti()

    useEffect(() => {
        if (firstDataWatch === 'arrived') {
            acknowledgeFirstData(trigger())
        }
    }, [firstDataWatch, trigger, acknowledgeFirstData])

    return <HogfettiComponent />
}
