import { useActions, useValues } from 'kea'

import { IconPlus, IconPlusSmall } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'
import { Button } from '@posthog/quill'

import { GoalLinesList } from 'lib/components/GoalLinesList'
import { useQuillSurface } from 'lib/components/QuillSurface/quillSurfaceContext'

import { InsightLogicProps } from '~/types'

import { goalLinesLogic } from './goalLinesLogic'

interface GoalLinesProps {
    insightProps: InsightLogicProps
}

export function GoalLines({ insightProps }: GoalLinesProps): JSX.Element {
    const { goalLines } = useValues(goalLinesLogic(insightProps))
    const { addGoalLine, updateGoalLine, removeGoalLine } = useActions(goalLinesLogic(insightProps))
    const quillSurface = useQuillSurface()

    if (quillSurface) {
        return (
            <div className="flex flex-col items-start gap-2">
                <GoalLinesList goalLines={goalLines} removeGoalLine={removeGoalLine} updateGoalLine={updateGoalLine} />
                <Button variant="outline" onClick={addGoalLine}>
                    <IconPlus />
                    Add goal line
                </Button>
            </div>
        )
    }

    return (
        <div>
            <GoalLinesList goalLines={goalLines} removeGoalLine={removeGoalLine} updateGoalLine={updateGoalLine} />
            <LemonButton
                type="secondary"
                onClick={addGoalLine}
                icon={<IconPlusSmall />}
                size="small"
                className={goalLines.length > 0 ? 'mt-2' : ''}
            >
                Add goal line
            </LemonButton>
        </div>
    )
}
