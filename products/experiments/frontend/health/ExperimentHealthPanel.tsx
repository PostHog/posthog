import { useActions, useValues } from 'kea'
import { useId, useState } from 'react'

import { IconChevronDown, IconChevronRight } from '@posthog/icons'
import { LemonButton, LemonCard, LemonTag } from '@posthog/lemon-ui'

import { experimentLogic } from 'scenes/experiments/experimentLogic'

import { EXPERIMENT_HEALTH_PANEL_ELEMENT_ID } from '../constants'
import { HealthCheckList } from './HealthCheckList'
import { HealthFindingRow } from './HealthFindingRow'
import { listedHealthChecks } from './healthPanelChecks'
import { healthIssues } from './healthPanelFindings'

export function ExperimentHealthPanel(): JSX.Element | null {
    const { healthFindings, healthChecks, healthExposureChecks } = useValues(experimentLogic)
    const { reportHealthChecksOpened } = useActions(experimentLogic)
    const [isCheckListOpen, setIsCheckListOpen] = useState(false)
    const checkListId = useId()

    // Without an issue the chip next to the experiment's status holds the checks, so the page keeps its space.
    if (healthFindings === null || healthChecks === null || healthIssues(healthFindings).length === 0) {
        return null
    }
    const listedChecks = listedHealthChecks(healthChecks)
    const exposureChecksMissing = healthExposureChecks === 'missing'

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
                {(listedChecks.length > 0 || exposureChecksMissing) && (
                    <>
                        <div className="px-1 py-1 border-t">
                            <LemonButton
                                size="xsmall"
                                type="tertiary"
                                sideIcon={isCheckListOpen ? <IconChevronDown /> : <IconChevronRight />}
                                onClick={() => {
                                    if (!isCheckListOpen) {
                                        reportHealthChecksOpened('panel')
                                    }
                                    setIsCheckListOpen(!isCheckListOpen)
                                }}
                                aria-expanded={isCheckListOpen}
                                aria-controls={checkListId}
                                data-attr="experiment-health-check-list-toggle"
                            >
                                Other checks
                            </LemonButton>
                        </div>
                        {isCheckListOpen && (
                            <HealthCheckList
                                id={checkListId}
                                checks={listedChecks}
                                exposureChecksMissing={exposureChecksMissing}
                            />
                        )}
                    </>
                )}
            </LemonCard>
        </section>
    )
}
