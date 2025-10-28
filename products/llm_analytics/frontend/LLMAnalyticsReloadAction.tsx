import { useActions, useValues } from 'kea'

import { IconRefresh } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { Spinner } from 'lib/lemon-ui/Spinner'

import { llmAnalyticsLogic } from './llmAnalyticsLogic'

export const LastRefreshText = (): JSX.Element => {
    const { newestRefreshed } = useValues(llmAnalyticsLogic)

    return newestRefreshed ? <span>Last updated {dayjs(newestRefreshed).fromNow()}</span> : <span>Refresh</span>
}

export function LLMAnalyticsReloadAction(): JSX.Element {
    const { isRefreshing } = useValues(llmAnalyticsLogic)
    const { refreshAllDashboardItems } = useActions(llmAnalyticsLogic)

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
