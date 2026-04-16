import { useActions } from 'kea'

import { IconRefresh, IconX } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { recommendationsTabLogic } from './recommendationsTabLogic'
import type { AlertsRecommendation } from './types'
import { ALERT_INFO } from './types'

export function AlertsRecommendationCard({
    recommendation,
    dismissed,
}: {
    recommendation: AlertsRecommendation
    dismissed?: boolean
}): JSX.Element | null {
    const { dismissRecommendation, restoreRecommendation, refreshRecommendation } = useActions(recommendationsTabLogic)
    const alerts = recommendation.meta.alerts ?? []
    const canRefresh = !recommendation.next_refresh_at || new Date(recommendation.next_refresh_at) <= new Date()

    if (alerts.length === 0) {
        return (
            <div className="border rounded-lg bg-surface-primary p-4">
                <h3 className="font-semibold text-sm m-0">Stay on top of issues</h3>
                <p className="text-xs text-secondary mt-1 mb-0">
                    You've already configured the recommended error tracking alerts.
                </p>
            </div>
        )
    }

    const enabledCount = alerts.filter((a) => a.enabled).length

    return (
        <div className="border rounded-lg bg-surface-primary p-4">
            <div className="flex items-center justify-between mb-1">
                <h3 className="font-semibold text-sm m-0">Stay on top of issues</h3>
                <div className="flex items-center gap-2">
                    <span className="text-xs text-muted">
                        {enabledCount} / {alerts.length} enabled
                    </span>
                    <div className="w-20 h-1.5 bg-border rounded-full">
                        <div
                            className="h-1.5 bg-success rounded-full"
                            // eslint-disable-next-line react/forbid-dom-props
                            style={{ width: `${(enabledCount / alerts.length) * 100}%` }}
                        />
                    </div>
                    <LemonButton
                        size="xsmall"
                        type="tertiary"
                        icon={<IconRefresh />}
                        onClick={() => refreshRecommendation(recommendation.id)}
                        disabledReason={!canRefresh ? 'Too early to refresh' : undefined}
                        tooltip="Refresh this recommendation"
                    />
                    {dismissed ? (
                        <LemonButton
                            size="xsmall"
                            type="tertiary"
                            onClick={() => restoreRecommendation(recommendation.id)}
                        >
                            Restore
                        </LemonButton>
                    ) : (
                        <LemonButton
                            size="xsmall"
                            type="tertiary"
                            icon={<IconX />}
                            onClick={() => dismissRecommendation(recommendation.id)}
                            tooltip="Dismiss this recommendation"
                        />
                    )}
                </div>
            </div>
            <p className="text-xs text-secondary mt-1 mb-3">
                Set up alerts to find out about new, recurring, and spiking issues.
            </p>
            <div className="flex flex-col gap-0">
                {alerts.map((alert) => {
                    const info = ALERT_INFO[alert.key]
                    if (!info) {
                        return null
                    }
                    return (
                        <div
                            key={alert.key}
                            className={`flex items-center gap-3 py-2 border-b last:border-b-0 ${alert.enabled ? 'opacity-60' : ''}`}
                        >
                            <div
                                className={`w-1.5 h-1.5 rounded-full shrink-0 ${alert.enabled ? 'bg-success' : 'bg-muted'}`}
                            />
                            <div className="flex-1">
                                <span className="text-sm font-medium">{info.name}</span>
                                <p className="text-xs text-muted m-0">{info.reason}</p>
                            </div>
                            {!alert.enabled && (
                                <LemonButton size="xsmall" type="secondary" to={info.enable_url}>
                                    Set up
                                </LemonButton>
                            )}
                        </div>
                    )
                })}
            </div>
        </div>
    )
}
