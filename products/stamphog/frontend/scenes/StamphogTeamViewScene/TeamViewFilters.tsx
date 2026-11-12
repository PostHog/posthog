import { useActions, useValues } from 'kea'

import { LemonInput, LemonSegmentedButton, LemonSelect } from '@posthog/lemon-ui'

import { TEAM_VIEW_OUTCOME_OPTIONS, TEAM_VIEW_WINDOW_OPTIONS } from './routingRunDisplay'
import { stamphogTeamViewSceneLogic } from './stamphogTeamViewSceneLogic'

export function TeamViewFilters(): JSX.Element {
    const { owner, outcome, windowDays, merged } = useValues(stamphogTeamViewSceneLogic)
    const { setOwner, setOutcome, setWindowDays, setMerged } = useActions(stamphogTeamViewSceneLogic)

    return (
        <div className="flex gap-2 flex-wrap items-center">
            <LemonInput
                value={owner}
                onChange={setOwner}
                placeholder="team-devex or @login"
                aria-label="Team or person"
                className="min-w-60"
                data-attr="stamphog-team-view-owner"
            />
            <LemonSegmentedButton
                value={outcome}
                onChange={setOutcome}
                options={TEAM_VIEW_OUTCOME_OPTIONS.map((option) => ({
                    ...option,
                    'data-attr': `stamphog-team-view-outcome-${option.value}`,
                }))}
                size="small"
            />
            <LemonSegmentedButton
                value={merged ? 'merged' : 'not_merged'}
                onChange={(value) => setMerged(value === 'merged')}
                options={[
                    { value: 'merged', label: 'Merged', 'data-attr': 'stamphog-team-view-merged' },
                    { value: 'not_merged', label: 'Not merged', 'data-attr': 'stamphog-team-view-not-merged' },
                ]}
                size="small"
            />
            <LemonSelect
                value={windowDays}
                onChange={setWindowDays}
                options={TEAM_VIEW_WINDOW_OPTIONS}
                size="small"
                data-attr="stamphog-team-view-window"
            />
        </div>
    )
}
