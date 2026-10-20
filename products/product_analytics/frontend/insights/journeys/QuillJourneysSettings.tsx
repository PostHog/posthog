import { useActions, useValues } from 'kea'

import { IconInfo } from '@posthog/icons'
import { Field, FieldLabel, Input, Text, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { PathCleaningControls } from 'lib/components/PathCleanFilters/PathCleaningControls'
import { QuillLabeledSwitch } from 'lib/components/QuillLabeledSwitch/QuillLabeledSwitch'

import { EditorFilterProps } from '~/types'

import { MAX_ROWS_PER_STEP_BOUNDS, MAX_STEPS_BOUNDS } from './editorBounds'
import { journeysDataLogic } from './journeysDataLogic'

function InfoTooltip({ children }: { children: React.ReactNode }): JSX.Element {
    return (
        <Tooltip>
            <TooltipTrigger render={<span className="inline-flex" tabIndex={0} aria-label="More info" />}>
                <IconInfo className="size-4 text-muted-foreground" />
            </TooltipTrigger>
            <TooltipContent className="max-w-80">{children}</TooltipContent>
        </Tooltip>
    )
}

export function QuillJourneysSettings({ insightProps }: EditorFilterProps): JSX.Element {
    const { pathsV2Filter, draftMaxSteps, draftMaxRowsPerStep } = useValues(journeysDataLogic(insightProps))
    const { updateInsightFilter, setDraftMaxSteps, setDraftMaxRowsPerStep, commitGridSize } = useActions(
        journeysDataLogic(insightProps)
    )

    const pathCleaningControls = (
        <PathCleaningControls
            localFilters={pathsV2Filter?.localPathCleaningFilters ?? []}
            setLocalFilters={(localPathCleaningFilters) => updateInsightFilter({ localPathCleaningFilters })}
            applyGlobal={pathsV2Filter?.applyTeamPathCleaning ?? true}
            setApplyGlobal={(applyTeamPathCleaning) => updateInsightFilter({ applyTeamPathCleaning })}
            data-attr="journeys-apply-team-path-cleaning"
        />
    )

    const onEnter = (e: React.KeyboardEvent<HTMLInputElement>): void => {
        if (e.key === 'Enter') {
            commitGridSize()
        }
    }
    const toNumber = (value: string): number | null => (value === '' ? null : Number(value))
    return (
        <div className="flex flex-col gap-4 mt-2">
            <div className="flex gap-4">
                <Field>
                    <FieldLabel htmlFor="journeys-max-steps" className="flex items-center gap-1">
                        Maximum steps
                        <InfoTooltip>How many steps of each journey are shown, as columns of the grid.</InfoTooltip>
                    </FieldLabel>
                    <Input
                        id="journeys-max-steps"
                        type="number"
                        min={MAX_STEPS_BOUNDS.min}
                        max={MAX_STEPS_BOUNDS.max}
                        value={draftMaxSteps ?? pathsV2Filter?.maxSteps ?? ''}
                        placeholder="5"
                        onChange={(e) => setDraftMaxSteps(toNumber(e.target.value))}
                        onBlur={commitGridSize}
                        onKeyDown={onEnter}
                        data-attr="journeys-max-steps"
                    />
                </Field>
                <Field>
                    <FieldLabel htmlFor="journeys-max-rows-per-step" className="flex items-center gap-1">
                        Rows per step
                        <InfoTooltip>
                            How many path items are shown per step. Items beyond this are grouped into the "Other" row.
                        </InfoTooltip>
                    </FieldLabel>
                    <Input
                        id="journeys-max-rows-per-step"
                        type="number"
                        min={MAX_ROWS_PER_STEP_BOUNDS.min}
                        max={MAX_ROWS_PER_STEP_BOUNDS.max}
                        value={draftMaxRowsPerStep ?? pathsV2Filter?.maxRowsPerStep ?? ''}
                        placeholder="3"
                        onChange={(e) => setDraftMaxRowsPerStep(toNumber(e.target.value))}
                        onBlur={commitGridSize}
                        onKeyDown={onEnter}
                        data-attr="journeys-max-rows-per-step"
                    />
                </Field>
            </div>
            <QuillLabeledSwitch
                checked={pathsV2Filter?.collapseRepeats ?? true}
                onChange={(collapseRepeats) => updateInsightFilter({ collapseRepeats })}
                label="Collapse repeated steps"
                tooltip="Merge immediate repeats of the same path item within a journey. For example, A → A → B becomes A → B."
                data-attr="journeys-collapse-repeats"
            />
            <div className="flex flex-col gap-2">
                <Text size="xs" weight="medium" render={<span />} className="flex items-center gap-1">
                    Path cleaning rules
                    <InfoTooltip>
                        Rules that rewrite path item names with regex, mostly to normalize URLs. Rules added here apply
                        only to this insight; rules from the project settings apply to all insights.
                    </InfoTooltip>
                </Text>
                {pathCleaningControls}
            </div>
        </div>
    )
}
