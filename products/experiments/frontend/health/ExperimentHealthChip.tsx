import { useValues } from 'kea'

import { IconWarning } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { pluralize } from 'lib/utils/strings'
import { experimentLogic } from 'scenes/experiments/experimentLogic'

import { EXPERIMENT_HEALTH_PANEL_ELEMENT_ID } from '../constants'
import { healthIssues } from './healthPanelFindings'

export function ExperimentHealthChip(): JSX.Element | null {
    const { healthFindings } = useValues(experimentLogic)
    const issues = healthIssues(healthFindings)

    if (!issues.length) {
        return null
    }

    const hasCritical = issues.some((finding) => finding.severity === 'critical')

    return (
        <LemonButton
            type="secondary"
            size="xsmall"
            icon={<IconWarning className={hasCritical ? 'text-danger' : 'text-warning'} />}
            onClick={() =>
                document.getElementById(EXPERIMENT_HEALTH_PANEL_ELEMENT_ID)?.scrollIntoView({ block: 'nearest' })
            }
            tooltip="Show the health checks"
            data-attr="experiment-health-chip"
        >
            {pluralize(issues.length, 'issue')}
        </LemonButton>
    )
}
