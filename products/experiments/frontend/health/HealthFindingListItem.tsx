import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { LemonButton } from '@posthog/lemon-ui'

import { experimentLogic } from 'scenes/experiments/experimentLogic'

import { HealthFindingSeverityIcon } from './HealthFindingSeverityIcon'
import { type HealthFindingGroup, reportedHealthFinding } from './healthPanelFindings'
import { useHealthFindingReporting } from './useHealthFindingReporting'

export function HealthFindingListItem({
    group,
    isSelected,
    onSelect,
}: {
    group: HealthFindingGroup
    isSelected: boolean
    /** Returns whether the pick puts the detail of the finding on screen. */
    onSelect: () => boolean
}): JSX.Element {
    const { finding, effects, severity } = group
    const { experimentLoadCount } = useValues(experimentLogic)
    const { reportHealthFindingShown, reportHealthFindingOpened } = useActions(experimentLogic)
    const { reportOpened } = useHealthFindingReporting(reportedHealthFinding(finding))
    const effectKeys = effects.map(({ code, subcode }) => `${code}:${subcode ?? ''}`).join(',')

    useEffect(() => {
        for (const effect of effects) {
            reportHealthFindingShown(reportedHealthFinding(effect, finding))
        }
        // The effects are a new array on each render, so their keys decide when they change.
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [effectKeys, experimentLoadCount, reportHealthFindingShown])

    return (
        <li>
            <LemonButton
                size="small"
                fullWidth
                active={isSelected}
                icon={<HealthFindingSeverityIcon severity={severity} />}
                onClick={() => {
                    if (onSelect()) {
                        // pinned: insights count `why` as opening the detail of a finding
                        reportOpened('why')
                        // The detail of the cause shows the findings it causes too.
                        for (const effect of effects) {
                            reportHealthFindingOpened(reportedHealthFinding(effect, finding), 'why')
                        }
                    }
                }}
                aria-current={isSelected ? 'true' : undefined}
                data-attr="experiment-health-finding"
            >
                <span className="flex flex-col gap-1">
                    <span className="font-semibold">{finding.title}</span>
                    {effects.length > 0 && (
                        <span className="flex flex-col gap-0.5 text-xs font-normal text-secondary">
                            <span>Also caused by this:</span>
                            <ul className="m-0 list-disc pl-4">
                                {effects.map((effect) => (
                                    <li key={`${effect.code}:${effect.subcode ?? ''}`}>{effect.title}</li>
                                ))}
                            </ul>
                        </span>
                    )}
                </span>
            </LemonButton>
        </li>
    )
}
