import { useActions, useValues } from 'kea'

import { IconPlus } from '@posthog/icons'
import { Button } from '@posthog/quill'

import type { InsightLogicProps } from '~/types'

import { ChartGoalLineRow } from './ChartGoalLineRow'
import { chartSettingsLogic } from './chartSettingsLogic'

export function ChartGoalLines({ insightProps }: { insightProps: InsightLogicProps }): JSX.Element {
    const { chartGoalLines } = useValues(chartSettingsLogic(insightProps))
    const { addGoalLine, changeGoalLine, removeGoalLine } = useActions(chartSettingsLogic(insightProps))

    return (
        <>
            {chartGoalLines.length > 0 && (
                <ul className="m-0 flex list-none flex-col gap-2 p-0">
                    {chartGoalLines.map((goalLine, index) => (
                        <ChartGoalLineRow
                            // The lines have no id, and their label and value change while they are edited.
                            key={index}
                            goalLine={goalLine}
                            position={index + 1}
                            onChange={(changes) => changeGoalLine(index, changes)}
                            onRemove={() => removeGoalLine(index)}
                        />
                    ))}
                </ul>
            )}
            <Button
                variant="outline"
                size="sm"
                className="self-start"
                onClick={() => addGoalLine()}
                data-attr="quill-insight-chart-setting-goal-line-add"
            >
                <IconPlus />
                Add goal line
            </Button>
        </>
    )
}
