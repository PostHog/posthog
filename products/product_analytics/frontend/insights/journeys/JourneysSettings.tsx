import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconGear } from '@posthog/icons'
import { LemonButton, LemonInput, LemonSwitch } from '@posthog/lemon-ui'

import { PathCleanFilters } from 'lib/components/PathCleanFilters/PathCleanFilters'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel/LemonLabel'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { EditorFilterProps } from '~/types'

import { journeysDataLogic } from './journeysDataLogic'

// Mirror the @minimum/@maximum bounds on PathsV2Filter, which the server enforces without clamping.
const MAX_STEPS_BOUNDS = { min: 2, max: 20 }
const MAX_ROWS_PER_STEP_BOUNDS = { min: 1, max: 10 }

export function JourneysSettings({ insightProps }: EditorFilterProps): JSX.Element {
    const { pathsV2Filter } = useValues(journeysDataLogic(insightProps))
    const { updateInsightFilter } = useActions(journeysDataLogic(insightProps))

    const { currentTeam } = useValues(teamLogic)
    const hasTeamCleaningRules = (currentTeam?.path_cleaning_filters || []).length > 0

    const [localGrid, setLocalGrid] = useState<{ maxSteps?: number; maxRowsPerStep?: number }>({
        maxSteps: pathsV2Filter?.maxSteps ?? undefined,
        maxRowsPerStep: pathsV2Filter?.maxRowsPerStep ?? undefined,
    })

    const commitGridSize = (): void => {
        if (
            localGrid.maxSteps !== (pathsV2Filter?.maxSteps ?? undefined) ||
            localGrid.maxRowsPerStep !== (pathsV2Filter?.maxRowsPerStep ?? undefined)
        ) {
            updateInsightFilter({ ...localGrid })
        }
    }

    return (
        <div className="flex flex-col gap-4 mt-2">
            <div className="flex gap-4">
                <div className="flex flex-col gap-1">
                    <LemonLabel info="How many steps of each journey are shown, as columns of the grid.">
                        Maximum steps
                    </LemonLabel>
                    <LemonInput
                        type="number"
                        min={MAX_STEPS_BOUNDS.min}
                        max={MAX_STEPS_BOUNDS.max}
                        value={localGrid.maxSteps}
                        placeholder="5"
                        onChange={(value) => setLocalGrid((state) => ({ ...state, maxSteps: value }))}
                        onBlur={commitGridSize}
                        onPressEnter={commitGridSize}
                        data-attr="journeys-max-steps"
                    />
                </div>
                <div className="flex flex-col gap-1">
                    <LemonLabel info='How many path items are shown per step. Items beyond this are grouped into the "Other" row.'>
                        Rows per step
                    </LemonLabel>
                    <LemonInput
                        type="number"
                        min={MAX_ROWS_PER_STEP_BOUNDS.min}
                        max={MAX_ROWS_PER_STEP_BOUNDS.max}
                        value={localGrid.maxRowsPerStep}
                        placeholder="3"
                        onChange={(value) => setLocalGrid((state) => ({ ...state, maxRowsPerStep: value }))}
                        onBlur={commitGridSize}
                        onPressEnter={commitGridSize}
                        data-attr="journeys-max-rows-per-step"
                    />
                </div>
            </div>
            <LemonSwitch
                checked={pathsV2Filter?.collapseRepeats ?? true}
                onChange={(collapseRepeats) => updateInsightFilter({ collapseRepeats })}
                label="Collapse repeated steps"
                tooltip="Merge immediate repeats of the same path item within a journey. For example, A → A → B becomes A → B."
                bordered
                fullWidth
                data-attr="journeys-collapse-repeats"
            />
            <div>
                <LemonLabel
                    className="mb-2"
                    info="Rules that rewrite path item names with regex, mostly to normalize URLs. Rules added here apply only to this insight; rules from the project settings apply to all insights."
                >
                    Path cleaning rules
                </LemonLabel>
                <PathCleanFilters
                    filters={pathsV2Filter?.localPathCleaningFilters ?? []}
                    setFilters={(localPathCleaningFilters) => updateInsightFilter({ localPathCleaningFilters })}
                />
                <Tooltip
                    title={
                        hasTeamCleaningRules
                            ? 'Apply the path cleaning rules from the project settings.'
                            : 'The project has no path cleaning rules. Configure them via the gear icon.'
                    }
                >
                    {/* This div is necessary for the tooltip to work. */}
                    <div className="inline-block mt-2 w-full">
                        <LemonSwitch
                            disabled={!hasTeamCleaningRules}
                            checked={hasTeamCleaningRules && (pathsV2Filter?.applyTeamPathCleaning ?? true)}
                            onChange={(applyTeamPathCleaning) => updateInsightFilter({ applyTeamPathCleaning })}
                            label={
                                <div className="flex items-center">
                                    <span>Apply global path URL cleaning</span>
                                    <LemonButton
                                        icon={<IconGear />}
                                        to={urls.settings('project-product-analytics', 'path-cleaning')}
                                        size="small"
                                        noPadding
                                        className="ml-1"
                                    />
                                </div>
                            }
                            bordered
                            fullWidth
                            data-attr="journeys-apply-team-path-cleaning"
                        />
                    </div>
                </Tooltip>
            </div>
        </div>
    )
}
