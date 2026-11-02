import { useValues } from 'kea'

import { LemonCard, LemonTag } from '@posthog/lemon-ui'

import { experimentLogic } from 'scenes/experiments/experimentLogic'

import { EXPERIMENT_HEALTH_PANEL_ELEMENT_ID } from '../constants'
import { HealthFindingRow } from './HealthFindingRow'
import { healthIssues } from './healthPanelFindings'

export function ExperimentHealthPanel(): JSX.Element | null {
    const { healthFindings } = useValues(experimentLogic)

    // The chip next to the experiment's status lists every check, so the panel shows the findings, and only with an issue.
    if (healthFindings === null || healthIssues(healthFindings).length === 0) {
        return null
    }

    return (
        <section
            id={EXPERIMENT_HEALTH_PANEL_ELEMENT_ID}
            aria-labelledby={`${EXPERIMENT_HEALTH_PANEL_ELEMENT_ID}-title`}
            data-attr="experiment-health-panel"
        >
            <LemonCard hoverEffect={false} className="p-0">
                <div className="flex items-center gap-2 px-3 py-2 border-b">
                    <h3 id={`${EXPERIMENT_HEALTH_PANEL_ELEMENT_ID}-title`} className="m-0 text-sm font-semibold">
                        Health checks
                    </h3>
                    <LemonTag type="completion">Beta</LemonTag>
                </div>
                <div className="divide-y">
                    {healthFindings.map((finding) => (
                        <HealthFindingRow key={`${finding.code}:${finding.subcode ?? ''}`} finding={finding} />
                    ))}
                </div>
            </LemonCard>
        </section>
    )
}
