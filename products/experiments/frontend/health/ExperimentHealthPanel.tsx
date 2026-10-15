import { useValues } from 'kea'

import { LemonCard } from '@posthog/lemon-ui'

import { experimentLogic } from 'scenes/experiments/experimentLogic'
import { experimentMetricsLogic } from 'scenes/experiments/experimentMetricsLogic'
import { metricResults } from 'scenes/experiments/utils'

import { EXPERIMENT_HEALTH_PANEL_ELEMENT_ID } from '../constants'
import { getTotalExposures } from './exposureHealth'
import { HealthFindingRow } from './HealthFindingRow'
import { lowPowerFinding } from './lowPowerFinding'

export function ExperimentHealthPanel(): JSX.Element | null {
    const { experiment, healthFindings, exposures, isExperimentDraft } = useValues(experimentLogic)
    const { primaryMetricsResults, primaryMetricsResultsErrors } = useValues(experimentMetricsLogic({ experiment }))

    if (healthFindings === null) {
        return null
    }

    // The page computes this finding from the metric results, which the health checks on the server don't read.
    // It is an info finding, so it goes last.
    const lowPower = lowPowerFinding({
        primaryMetrics: metricResults(experiment)(primaryMetricsResults, primaryMetricsResultsErrors, 'primary'),
        totalExposures: getTotalExposures(exposures),
        recommendedSampleSize: experiment.running_time_calculation?.recommended_sample_size,
        isExperimentDraft,
    })
    const findings = lowPower ? [...healthFindings, lowPower] : healthFindings

    if (!findings.length) {
        return null
    }

    return (
        <section
            id={EXPERIMENT_HEALTH_PANEL_ELEMENT_ID}
            aria-labelledby={`${EXPERIMENT_HEALTH_PANEL_ELEMENT_ID}-title`}
            data-attr="experiment-health-panel"
        >
            <LemonCard hoverEffect={false} className="p-0">
                <h3
                    id={`${EXPERIMENT_HEALTH_PANEL_ELEMENT_ID}-title`}
                    className="m-0 px-3 py-2 border-b text-sm font-semibold"
                >
                    Health checks
                </h3>
                <div className="divide-y">
                    {findings.map((finding) => (
                        <HealthFindingRow key={`${finding.code}:${finding.subcode ?? ''}`} finding={finding} />
                    ))}
                </div>
            </LemonCard>
        </section>
    )
}
