import { useActions, useValues } from 'kea'

import { IconWarning } from '@posthog/icons'
import { LemonButton, LemonDropdown, Spinner } from '@posthog/lemon-ui'

import { pluralize } from 'lib/utils/strings'
import { experimentLogic } from 'scenes/experiments/experimentLogic'

import { EXPERIMENT_HEALTH_PANEL_ELEMENT_ID } from '../constants'
import { HealthChecksOverview } from './HealthChecksOverview'
import { healthChipState } from './healthPanelChecks'

export function ExperimentHealthChip(): JSX.Element | null {
    const { healthFindings, healthChecks, healthExposureChecks, isExperimentDraft } = useValues(experimentLogic)
    const { reportHealthChecksOpened } = useActions(experimentLogic)
    const state = healthChipState(healthFindings, healthChecks, healthExposureChecks)

    switch (state.kind) {
        case 'hidden':
            return null
        case 'issues':
            return (
                <LemonButton
                    type="secondary"
                    size="xsmall"
                    icon={<IconWarning className={state.hasCritical ? 'text-danger' : 'text-warning'} />}
                    onClick={() =>
                        document
                            .getElementById(EXPERIMENT_HEALTH_PANEL_ELEMENT_ID)
                            ?.scrollIntoView({ block: 'nearest' })
                    }
                    tooltip="Show the health checks"
                    data-attr="experiment-health-chip"
                >
                    {pluralize(state.count, 'issue')}
                </LemonButton>
            )
        case 'pending':
            return (
                <span className="flex items-center gap-1 text-secondary" data-attr="experiment-health-chip-pending">
                    <Spinner className="text-sm" />
                    <span>Checking health</span>
                </span>
            )
        case 'checks':
            return (
                <LemonDropdown
                    overlay={
                        <HealthChecksOverview
                            checks={state.checks}
                            notes={state.notes}
                            isDraft={isExperimentDraft}
                            exposureChecksMissing={healthExposureChecks === 'missing'}
                        />
                    }
                    closeOnClickInside={false}
                    placement="bottom-start"
                    onVisibilityChange={(visible) => {
                        if (visible) {
                            reportHealthChecksOpened('meta_bar')
                        }
                    }}
                >
                    <LemonButton
                        type="tertiary"
                        size="xsmall"
                        tooltip="Health checks"
                        data-attr="experiment-health-checks-button"
                    >
                        <span className="font-normal">{state.label}</span>
                    </LemonButton>
                </LemonDropdown>
            )
    }
}
