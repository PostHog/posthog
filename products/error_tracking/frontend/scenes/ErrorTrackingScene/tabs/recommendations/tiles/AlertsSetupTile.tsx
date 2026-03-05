import { IconBell } from '@posthog/icons'
import { LemonButton, LemonTag } from '@posthog/lemon-ui'

import { RecommendationTile } from '../RecommendationTile'

export interface MissingAlert {
    type: 'issue_created' | 'issue_reopened' | 'issue_spiking'
    label: string
    description: string
}

const ALERT_ICON_COLORS: Record<string, string> = {
    issue_created: 'text-success',
    issue_reopened: 'text-warning',
    issue_spiking: 'text-danger',
}

export function AlertsSetupTile({ missingAlerts }: { missingAlerts: MissingAlert[] }): JSX.Element {
    return (
        <RecommendationTile
            tileId="alerts-setup"
            icon={<IconBell className="text-link" />}
            title="Missing alert configurations"
            category="Alerts"
            priority="setup"
        >
            <p className="text-xs text-secondary mb-2">
                Stay on top of your errors by enabling these alerts. You'll be notified when important events happen.
            </p>
            <div className="space-y-2">
                {missingAlerts.map((alert) => (
                    <div key={alert.type} className="flex items-center gap-3 bg-surface-alt rounded-lg px-3 py-2.5">
                        <div className={`w-2 h-2 rounded-full shrink-0 ${ALERT_ICON_COLORS[alert.type]} bg-current`} />
                        <div className="flex-1 min-w-0">
                            <div className="flex items-center gap-2">
                                <span className="text-sm font-medium">{alert.label}</span>
                                <LemonTag type="muted" size="small">
                                    Not configured
                                </LemonTag>
                            </div>
                            <p className="text-xs text-secondary mb-0 mt-0.5">{alert.description}</p>
                        </div>
                        <LemonButton size="xsmall" type="primary" className="shrink-0">
                            Create alert
                        </LemonButton>
                    </div>
                ))}
            </div>
        </RecommendationTile>
    )
}
