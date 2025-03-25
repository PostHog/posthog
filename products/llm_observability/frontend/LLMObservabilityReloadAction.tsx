import { LemonButton } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { dayjs } from 'lib/dayjs'
import { IconRefresh } from 'lib/lemon-ui/icons'
import { Spinner } from 'lib/lemon-ui/Spinner'

import { llmObservabilityLogic } from './llmObservabilityLogic'

export const LastRefreshText = (): JSX.Element => {
    const { newestRefreshed } = useValues(llmObservabilityLogic)

    return newestRefreshed ? <span>Last updated {dayjs(newestRefreshed).fromNow()}</span> : <span>Refresh</span>
}

export function LLMObservabilityReloadAction(): JSX.Element {
    const { isRefreshing } = useValues(llmObservabilityLogic)
    const { refreshAllDashboardItems } = useActions(llmObservabilityLogic)

    return (
        <div className="relative">
            <LemonButton
                onClick={refreshAllDashboardItems}
                type="secondary"
                icon={isRefreshing ? <Spinner textColored /> : <IconRefresh />}
                size="small"
                disabledReason={isRefreshing ? 'Refreshing...' : undefined}
            >
                <span className="dashboard-items-action-refresh-text">
                    {isRefreshing ? <>Refreshing...</> : <LastRefreshText />}
                </span>
            </LemonButton>
        </div>
    )
}
