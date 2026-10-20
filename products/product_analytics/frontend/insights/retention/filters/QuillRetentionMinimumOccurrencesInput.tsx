import { useActions, useValues } from 'kea'
import { toast } from 'react-toastify'

import { Input, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { insightLogic } from 'scenes/insights/insightLogic'

import { retentionLogic } from '../retentionLogic'

export function QuillRetentionMinimumOccurrencesInput(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { retentionFilter } = useValues(retentionLogic(insightProps))
    const { updateInsightFilter } = useActions(retentionLogic(insightProps))
    const { minimumOccurrences = 1 } = retentionFilter || {}

    return (
        <Tooltip>
            <TooltipTrigger
                render={
                    <Input
                        type="number"
                        className="w-20"
                        aria-label="Minimum occurrences"
                        defaultValue={minimumOccurrences}
                        min={1}
                        onBlur={({ target }) => {
                            let newValue = Number(target.value)
                            if (newValue < 1) {
                                newValue = 1
                                toast.warn(
                                    <>
                                        The minimum number of occurrences is <strong>1</strong>
                                    </>
                                )
                            }
                            target.value = newValue.toString()
                            updateInsightFilter({ minimumOccurrences: newValue })
                        }}
                    />
                }
            />
            <TooltipContent className="max-w-80">
                Counts users as retained only if they return at least this number of times during the interval. For
                example, if set to 2 and the interval is a week, users must return 2 or more times within the week to be
                considered retained.
            </TooltipContent>
        </Tooltip>
    )
}
