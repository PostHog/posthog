import { useActions, useValues } from 'kea'

import { LemonInput, LemonSwitch } from '@posthog/lemon-ui'

import { PathCleaningControls } from 'lib/components/PathCleanFilters/PathCleaningControls'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel/LemonLabel'

import { EditorFilterProps } from '~/types'

import { MAX_ROWS_PER_STEP_BOUNDS, MAX_STEPS_BOUNDS } from './editorBounds'
import { journeysDataLogic } from './journeysDataLogic'

export function JourneysSettings({ insightProps }: EditorFilterProps): JSX.Element {
    const { pathsV2Filter, draftMaxSteps, draftMaxRowsPerStep } = useValues(journeysDataLogic(insightProps))
    const { updateInsightFilter, setDraftMaxSteps, setDraftMaxRowsPerStep, commitGridSize } = useActions(
        journeysDataLogic(insightProps)
    )

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
                        value={draftMaxSteps ?? pathsV2Filter?.maxSteps ?? undefined}
                        placeholder="5"
                        onChange={(value) => setDraftMaxSteps(value ?? null)}
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
                        value={draftMaxRowsPerStep ?? pathsV2Filter?.maxRowsPerStep ?? undefined}
                        placeholder="3"
                        onChange={(value) => setDraftMaxRowsPerStep(value ?? null)}
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
                <PathCleaningControls
                    localFilters={pathsV2Filter?.localPathCleaningFilters ?? []}
                    setLocalFilters={(localPathCleaningFilters) => updateInsightFilter({ localPathCleaningFilters })}
                    applyGlobal={pathsV2Filter?.applyTeamPathCleaning ?? true}
                    setApplyGlobal={(applyTeamPathCleaning) => updateInsightFilter({ applyTeamPathCleaning })}
                    data-attr="journeys-apply-team-path-cleaning"
                />
            </div>
        </div>
    )
}
