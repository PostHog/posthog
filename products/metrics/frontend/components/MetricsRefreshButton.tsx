import { useActions, useValues } from 'kea'

import { IconRefresh } from '@posthog/icons'
import { LemonButton, LemonSwitch } from '@posthog/lemon-ui'

import { LIVE_REFRESH_MS, metricsViewerLogic } from './metricsViewerLogic'

export function MetricsRefreshButton({
    disabledReason,
    noQueryReason,
}: {
    disabledReason: string | null
    noQueryReason: string | undefined
}): JSX.Element {
    const { liveRefresh, queryLoading } = useValues(metricsViewerLogic)
    const { setLiveRefresh, refresh } = useActions(metricsViewerLogic)
    const refreshSeconds = LIVE_REFRESH_MS / 1000

    return (
        <LemonButton
            size="small"
            type="secondary"
            icon={<IconRefresh />}
            onClick={() => refresh()}
            loading={queryLoading}
            tooltip={liveRefresh ? `Refreshing every ${refreshSeconds}s` : 'Refresh'}
            disabledReason={disabledReason ?? noQueryReason}
            data-attr="metrics-viewer-refresh"
            sideAction={{
                'data-attr': 'metrics-viewer-refresh-options',
                tooltip: 'Auto-refresh',
                dropdown: {
                    placement: 'bottom-end',
                    actionable: true,
                    closeOnClickInside: false,
                    overlay: (
                        <div className="p-1">
                            <LemonSwitch
                                label={`Auto-refresh every ${refreshSeconds}s`}
                                checked={liveRefresh}
                                onChange={setLiveRefresh}
                                data-attr="metrics-viewer-live-toggle"
                                disabledReason={disabledReason}
                            />
                        </div>
                    ),
                },
            }}
        >
            {liveRefresh ? `Every ${refreshSeconds}s` : null}
        </LemonButton>
    )
}
