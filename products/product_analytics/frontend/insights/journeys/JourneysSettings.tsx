import { useActions, useValues } from 'kea'

import { LemonInput, LemonSelect, LemonSelectOption, LemonSwitch } from '@posthog/lemon-ui'

import { PathCleaningControls } from 'lib/components/PathCleanFilters/PathCleaningControls'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel/LemonLabel'
import { capitalizeFirstLetter, pluralize } from 'lib/utils/strings'
import { TIME_INTERVAL_BOUNDS } from 'scenes/funnels/funnelUtils'

import { EditorFilterProps, FunnelConversionWindowTimeUnit } from '~/types'

import { MAX_ROWS_PER_STEP_BOUNDS, MAX_STEPS_BOUNDS } from './editorBounds'
import { journeysDataLogic } from './journeysDataLogic'

export function JourneysSettings({ insightProps }: EditorFilterProps): JSX.Element {
    const { pathsV2Filter, draftMaxSteps, draftMaxRowsPerStep, timeWindow, draftTimeWindowInterval, isAnchored } =
        useValues(journeysDataLogic(insightProps))
    const {
        updateInsightFilter,
        setDraftMaxSteps,
        setDraftMaxRowsPerStep,
        commitGridSize,
        setDraftTimeWindow,
        setTimeWindowUnit,
        commitTimeWindow,
    } = useActions(journeysDataLogic(insightProps))

    const displayInterval = draftTimeWindowInterval ?? timeWindow.interval
    const intervalBounds = TIME_INTERVAL_BOUNDS[timeWindow.unit]
    const unitOptions: LemonSelectOption<FunnelConversionWindowTimeUnit>[] = Object.keys(TIME_INTERVAL_BOUNDS).map(
        (unit) => ({
            label: capitalizeFirstLetter(pluralize(displayInterval, unit, `${unit}s`, false)),
            value: unit as FunnelConversionWindowTimeUnit,
        })
    )

    return (
        <div className="flex flex-col gap-4 mt-2">
            <div className="flex flex-col gap-1">
                <LemonLabel
                    info={
                        isAnchored
                            ? 'How much time around the anchor counts toward each journey. Funnels opened from this chart use the same window.'
                            : 'How long someone can pause before their next event starts a new journey.'
                    }
                >
                    {isAnchored ? 'Conversion window' : 'Inactivity gap'}
                </LemonLabel>
                <div className="flex items-center gap-2">
                    <LemonInput
                        type="number"
                        className="max-w-20"
                        fullWidth={false}
                        min={intervalBounds[0]}
                        max={intervalBounds[1]}
                        value={displayInterval}
                        onChange={(value) => setDraftTimeWindow(value ?? null)}
                        onBlur={commitTimeWindow}
                        onPressEnter={commitTimeWindow}
                        data-attr="journeys-time-window-interval"
                    />
                    <LemonSelect
                        dropdownMatchSelectWidth={false}
                        value={timeWindow.unit}
                        onChange={(unit) => unit && setTimeWindowUnit(unit)}
                        options={unitOptions}
                        data-attr="journeys-time-window-unit"
                    />
                </div>
            </div>
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
