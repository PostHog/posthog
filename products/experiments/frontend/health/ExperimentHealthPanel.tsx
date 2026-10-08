import { useValues } from 'kea'

import { experimentLogic } from 'scenes/experiments/experimentLogic'

import { EXPERIMENT_HEALTH_PANEL_ELEMENT_ID } from '../constants'
import { HealthFindingRow } from './HealthFindingRow'

export function ExperimentHealthPanel(): JSX.Element | null {
    const { healthFindings } = useValues(experimentLogic)

    if (!healthFindings?.length) {
        return null
    }

    return (
        <section
            id={EXPERIMENT_HEALTH_PANEL_ELEMENT_ID}
            className="border rounded bg-surface-primary"
            aria-labelledby={`${EXPERIMENT_HEALTH_PANEL_ELEMENT_ID}-title`}
            data-attr="experiment-health-panel"
        >
            <h3
                id={`${EXPERIMENT_HEALTH_PANEL_ELEMENT_ID}-title`}
                className="m-0 px-3 py-2 border-b text-sm font-semibold"
            >
                Health checks
            </h3>
            <div className="divide-y">
                {healthFindings.map((finding) => (
                    <HealthFindingRow key={`${finding.code}:${finding.subcode ?? ''}`} finding={finding} />
                ))}
            </div>
        </section>
    )
}
