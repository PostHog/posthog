import { useActions, useValues } from 'kea'
import { useId } from 'react'

import { IconInfo } from '@posthog/icons'
import { LemonInput, LemonSwitch } from '@posthog/lemon-ui'
import { Field, FieldTitle, Input, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { QuillChartOptionLabel } from 'lib/components/ChartOptions/QuillChartOptionLabel'
import { QuillChartOptionSwitch } from 'lib/components/ChartOptions/QuillChartOptionSwitch'
import { PathCleaningControls } from 'lib/components/PathCleanFilters/PathCleaningControls'
import { useQuillSurface } from 'lib/components/QuillSurface/quillSurfaceContext'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel/LemonLabel'

import { EditorFilterProps } from '~/types'

import { MAX_ROWS_PER_STEP_BOUNDS, MAX_STEPS_BOUNDS } from './editorBounds'
import { journeysDataLogic } from './journeysDataLogic'

const MAX_STEPS_INFO = 'How many steps of each journey are shown, as columns of the grid.'
const MAX_ROWS_PER_STEP_INFO =
    'How many path items are shown per step. Items beyond this are grouped into the "Other" row.'
const PATH_CLEANING_INFO =
    'Rules that rewrite path item names with regex, mostly to normalize URLs. Rules added here apply only to this insight; rules from the project settings apply to all insights.'
const COLLAPSE_REPEATS_INFO =
    'Merge immediate repeats of the same path item within a journey. For example, A → A → B becomes A → B.'

export function JourneysSettings({ insightProps }: EditorFilterProps): JSX.Element {
    const { pathsV2Filter, draftMaxSteps, draftMaxRowsPerStep } = useValues(journeysDataLogic(insightProps))
    const { updateInsightFilter, setDraftMaxSteps, setDraftMaxRowsPerStep, commitGridSize } = useActions(
        journeysDataLogic(insightProps)
    )
    const quillSurface = useQuillSurface()
    const maxStepsId = useId()
    const maxRowsPerStepId = useId()

    const maxSteps = draftMaxSteps ?? pathsV2Filter?.maxSteps ?? undefined
    const maxRowsPerStep = draftMaxRowsPerStep ?? pathsV2Filter?.maxRowsPerStep ?? undefined
    const onMaxStepsChange = (value: number | undefined): void => setDraftMaxSteps(value ?? null)
    const onMaxRowsPerStepChange = (value: number | undefined): void => setDraftMaxRowsPerStep(value ?? null)
    const commitOnEnter = (event: React.KeyboardEvent<HTMLInputElement>): void => {
        if (event.key === 'Enter') {
            commitGridSize()
        }
    }
    const pathCleaningControls = (
        <PathCleaningControls
            localFilters={pathsV2Filter?.localPathCleaningFilters ?? []}
            setLocalFilters={(localPathCleaningFilters) => updateInsightFilter({ localPathCleaningFilters })}
            applyGlobal={pathsV2Filter?.applyTeamPathCleaning ?? true}
            setApplyGlobal={(applyTeamPathCleaning) => updateInsightFilter({ applyTeamPathCleaning })}
            data-attr="journeys-apply-team-path-cleaning"
        />
    )

    if (quillSurface) {
        return (
            <div className="flex flex-col gap-4">
                <Field orientation="horizontal" className="justify-between">
                    <QuillChartOptionLabel htmlFor={maxStepsId} label="Maximum steps" info={MAX_STEPS_INFO} />
                    <Input
                        id={maxStepsId}
                        type="number"
                        className="w-28"
                        min={MAX_STEPS_BOUNDS.min}
                        max={MAX_STEPS_BOUNDS.max}
                        value={maxSteps === undefined || Number.isNaN(maxSteps) ? '' : maxSteps}
                        placeholder="5"
                        onChange={(event) => onMaxStepsChange(event.currentTarget.valueAsNumber)}
                        onBlur={commitGridSize}
                        onKeyDown={commitOnEnter}
                        data-attr="journeys-max-steps"
                    />
                </Field>
                <Field orientation="horizontal" className="justify-between">
                    <QuillChartOptionLabel
                        htmlFor={maxRowsPerStepId}
                        label="Rows per step"
                        info={MAX_ROWS_PER_STEP_INFO}
                    />
                    <Input
                        id={maxRowsPerStepId}
                        type="number"
                        className="w-28"
                        min={MAX_ROWS_PER_STEP_BOUNDS.min}
                        max={MAX_ROWS_PER_STEP_BOUNDS.max}
                        value={maxRowsPerStep === undefined || Number.isNaN(maxRowsPerStep) ? '' : maxRowsPerStep}
                        placeholder="3"
                        onChange={(event) => onMaxRowsPerStepChange(event.currentTarget.valueAsNumber)}
                        onBlur={commitGridSize}
                        onKeyDown={commitOnEnter}
                        data-attr="journeys-max-rows-per-step"
                    />
                </Field>
                <QuillChartOptionSwitch
                    label="Collapse repeated steps"
                    info={COLLAPSE_REPEATS_INFO}
                    checked={pathsV2Filter?.collapseRepeats ?? true}
                    onChange={(collapseRepeats) => updateInsightFilter({ collapseRepeats })}
                    data-attr="journeys-collapse-repeats"
                />
                <Field>
                    <FieldTitle className="items-center gap-1 font-normal">
                        Path cleaning rules
                        <Tooltip>
                            <TooltipTrigger
                                render={<span className="inline-flex text-muted-foreground" />}
                                aria-label="More info"
                            >
                                <IconInfo />
                            </TooltipTrigger>
                            <TooltipContent>{PATH_CLEANING_INFO}</TooltipContent>
                        </Tooltip>
                    </FieldTitle>
                    {pathCleaningControls}
                </Field>
            </div>
        )
    }

    return (
        <div className="flex flex-col gap-4 mt-2">
            <div className="flex gap-4">
                <div className="flex flex-col gap-1">
                    <LemonLabel info={MAX_STEPS_INFO}>Maximum steps</LemonLabel>
                    <LemonInput
                        type="number"
                        min={MAX_STEPS_BOUNDS.min}
                        max={MAX_STEPS_BOUNDS.max}
                        value={maxSteps}
                        placeholder="5"
                        onChange={onMaxStepsChange}
                        onBlur={commitGridSize}
                        onPressEnter={commitGridSize}
                        data-attr="journeys-max-steps"
                    />
                </div>
                <div className="flex flex-col gap-1">
                    <LemonLabel info={MAX_ROWS_PER_STEP_INFO}>Rows per step</LemonLabel>
                    <LemonInput
                        type="number"
                        min={MAX_ROWS_PER_STEP_BOUNDS.min}
                        max={MAX_ROWS_PER_STEP_BOUNDS.max}
                        value={maxRowsPerStep}
                        placeholder="3"
                        onChange={onMaxRowsPerStepChange}
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
                tooltip={COLLAPSE_REPEATS_INFO}
                bordered
                fullWidth
                data-attr="journeys-collapse-repeats"
            />
            <div>
                <LemonLabel className="mb-2" info={PATH_CLEANING_INFO}>
                    Path cleaning rules
                </LemonLabel>
                {pathCleaningControls}
            </div>
        </div>
    )
}
