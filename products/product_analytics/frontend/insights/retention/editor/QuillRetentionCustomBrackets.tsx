import { useActions, useValues } from 'kea'

import { IconPlus, IconTrash } from '@posthog/icons'
import { Button, Input, Text, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { QuillIconButton } from 'lib/components/QuillIconButton/QuillIconButton'
import { QuillSelect } from 'lib/components/QuillSelect/QuillSelect'
import { getOrdinalSuffix } from 'lib/utils/strings'

import { EditorFilterProps, RetentionPeriod } from '~/types'

import { dateOptionPlurals, dateOptions } from '../constants'
import { MAX_BRACKETS, retentionLogic } from '../retentionLogic'
import { MAX_RANGE, getRetentionBracketLabel } from './retentionConditionUtils'

export function QuillRetentionCustomBrackets({
    insightProps,
}: {
    insightProps: EditorFilterProps['insightProps']
}): JSX.Element {
    const { retentionFilter, localCustomBrackets } = useValues(retentionLogic(insightProps))
    const { updateInsightFilter, updateLocalCustomBracket, addCustomBracket, removeCustomBracket } = useActions(
        retentionLogic(insightProps)
    )
    const { period, retentionCustomBrackets } = retentionFilter || {}
    const unit = dateOptionPlurals[period || 'Day'].toLowerCase().slice(0, -1)
    const totalRange = (retentionCustomBrackets || []).reduce((acc: number, val: number) => acc + val, 0)
    const reachedMax = localCustomBrackets.length >= MAX_BRACKETS

    return (
        <div className="flex flex-col gap-2">
            <div className="flex items-center gap-2">
                <span>Bracket by</span>
                <QuillSelect
                    value={period ?? RetentionPeriod.Day}
                    onChange={(value) => updateInsightFilter({ period: value })}
                    options={dateOptions.map((option) => ({
                        value: option,
                        label: dateOptionPlurals[option] || option,
                    }))}
                />
            </div>
            {localCustomBrackets.slice(0, MAX_BRACKETS).map((bracket, index) => {
                const ordinal = `${index + 1}${getOrdinalSuffix(index + 1)}`
                const bracketLabel = getRetentionBracketLabel(localCustomBrackets, index, unit)
                return (
                    <div key={index} className="flex items-center gap-2">
                        <span className="w-24">{ordinal} bracket</span>
                        <Input
                            type="number"
                            className="w-20"
                            aria-label={`${ordinal} bracket`}
                            value={typeof bracket === 'number' ? bracket : ''}
                            min={1}
                            onChange={(e) =>
                                updateLocalCustomBracket(
                                    index,
                                    e.target.value === '' ? undefined : Number(e.target.value)
                                )
                            }
                        />
                        <QuillIconButton
                            label="Remove bracket"
                            icon={<IconTrash />}
                            onClick={() => removeCustomBracket(index)}
                            disabledReason={
                                localCustomBrackets.length === 1 ? 'You must have at least one bracket' : null
                            }
                        />
                        {bracketLabel ? <span>{bracketLabel}</span> : null}
                    </div>
                )
            })}
            <div>
                <Tooltip disabled={!reachedMax}>
                    <TooltipTrigger render={<Button onClick={() => addCustomBracket()} disabled={reachedMax} />}>
                        <IconPlus />
                        Add another bracket
                    </TooltipTrigger>
                    <TooltipContent>You have reached the maximum number of brackets</TooltipContent>
                </Tooltip>
            </div>
            {totalRange > MAX_RANGE ? (
                <Text size="xs" variant="destructive" className="m-0">
                    Total range is too large.
                </Text>
            ) : null}
        </div>
    )
}
