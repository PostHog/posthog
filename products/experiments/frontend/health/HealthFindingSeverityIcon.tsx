import { IconInfo, IconWarning } from '@posthog/icons'
import { Tooltip } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'

import { HEALTH_FINDING_SEVERITY_LABELS, type HealthPanelFinding } from './healthPanelFindings'

export function HealthFindingSeverityIcon({ severity }: { severity: HealthPanelFinding['severity'] }): JSX.Element {
    return (
        <Tooltip title={HEALTH_FINDING_SEVERITY_LABELS[severity]}>
            <span role="img" aria-label={HEALTH_FINDING_SEVERITY_LABELS[severity]} className="flex shrink-0">
                {severity === 'info' ? (
                    <IconInfo className="text-secondary" />
                ) : (
                    <IconWarning className={cn(severity === 'critical' ? 'text-danger' : 'text-warning')} />
                )}
            </span>
        </Tooltip>
    )
}
