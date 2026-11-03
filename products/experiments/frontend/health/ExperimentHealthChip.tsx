import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconWarning } from '@posthog/icons'
import { LemonButton, LemonDropdown, Spinner } from '@posthog/lemon-ui'

import { pluralize } from 'lib/utils/strings'
import { experimentLogic } from 'scenes/experiments/experimentLogic'

import { HealthChecksOverview } from './HealthChecksOverview'
import { healthChipState } from './healthPanelChecks'

export function ExperimentHealthChip(): JSX.Element | null {
    const { healthFindings, healthChecks, healthExposureChecks, isExperimentDraft } = useValues(experimentLogic)
    const { reportHealthChecksOpened } = useActions(experimentLogic)
    const [isOverviewOpen, setIsOverviewOpen] = useState(false)
    const state = healthChipState(healthFindings, healthChecks, healthExposureChecks)

    if (state.kind === 'hidden') {
        return null
    }
    if (state.kind === 'pending') {
        return (
            <span className="flex items-center gap-1 text-secondary" data-attr="experiment-health-chip-pending">
                <Spinner className="text-sm" />
                <span>Checking health</span>
            </span>
        )
    }
    // The same overview opens with and without issues, so the reader finds the checks behind either label.
    return (
        <LemonDropdown
            overlay={
                <HealthChecksOverview
                    checks={state.checks}
                    findings={state.findings}
                    isDraft={isExperimentDraft}
                    exposureChecksMissing={healthExposureChecks === 'missing'}
                    // Most actions open a modal, and a modal renders below a popover, so the overview closes first.
                    onFindingActedOn={() => setIsOverviewOpen(false)}
                />
            }
            visible={isOverviewOpen}
            closeOnClickInside={false}
            placement="bottom-start"
            onVisibilityChange={(visible) => {
                setIsOverviewOpen(visible)
                if (visible) {
                    reportHealthChecksOpened('meta_bar')
                }
            }}
        >
            {state.kind === 'issues' ? (
                <LemonButton
                    type="secondary"
                    size="xsmall"
                    icon={<IconWarning className={state.hasCritical ? 'text-danger' : 'text-warning'} />}
                    tooltip="Show the health checks"
                    data-attr="experiment-health-chip"
                >
                    {pluralize(state.count, 'issue')}
                </LemonButton>
            ) : (
                <LemonButton
                    type="tertiary"
                    size="xsmall"
                    tooltip="Health checks"
                    data-attr="experiment-health-checks-button"
                >
                    <span className="font-normal">{state.label}</span>
                </LemonButton>
            )}
        </LemonDropdown>
    )
}
