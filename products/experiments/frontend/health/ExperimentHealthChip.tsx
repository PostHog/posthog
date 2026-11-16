import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { IconWarning } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { pluralize } from 'lib/utils/strings'
import { experimentLogic } from 'scenes/experiments/experimentLogic'
import { experimentSceneLogic } from 'scenes/experiments/experimentSceneLogic'

import { healthChipState } from './healthPanelChecks'
import { healthIssueGroups, reportedHealthFinding } from './healthPanelFindings'

export function ExperimentHealthChip(): JSX.Element | null {
    const { healthFindings, experimentLoadCount } = useValues(experimentLogic)
    const { reportHealthChecksOpened, reportHealthFindingShown } = useActions(experimentLogic)
    const { setActiveTabKey } = useActions(experimentSceneLogic)
    const state = healthChipState(healthFindings)

    // The chip is the sign of an issue on every tab, so it reports the issues as shown on load, each finding of an
    // issue with the cause it shows under. The logic reports each finding once per load, so the health tab does not
    // report them again.
    useEffect(() => {
        for (const { finding, effects } of healthIssueGroups(healthFindings)) {
            reportHealthFindingShown(reportedHealthFinding(finding))
            for (const effect of effects) {
                reportHealthFindingShown(reportedHealthFinding(effect, finding))
            }
        }
    }, [healthFindings, experimentLoadCount, reportHealthFindingShown])

    if (state.kind === 'hidden') {
        return null
    }
    const openHealthTab = (): void => {
        setActiveTabKey('health')
        reportHealthChecksOpened('meta_bar')
    }
    return (
        <LemonButton
            type="secondary"
            size="xsmall"
            icon={<IconWarning className={state.hasCritical ? 'text-danger' : 'text-warning'} />}
            tooltip="Show the health checks"
            onClick={openHealthTab}
            data-attr="experiment-health-chip"
        >
            {pluralize(state.count, 'issue')}
        </LemonButton>
    )
}
