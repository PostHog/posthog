import { useActions, useValues } from 'kea'
import { toast } from 'react-toastify'

import { LemonInput, Tooltip } from '@posthog/lemon-ui'
import { Input, Tooltip as QuillTooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { useQuillSurface } from 'lib/components/QuillSurface/quillSurfaceContext'
import { insightLogic } from 'scenes/insights/insightLogic'

import { retentionLogic } from '../retentionLogic'

const MINIMUM_OCCURRENCES_INFO =
    'Counts users as retained only if they return at least this number of times during the interval. For example, if set to 2 and the interval is a week, users must return 2 or more times within the week to be considered retained.'

export function RetentionMinimumOccurrencesInput(): JSX.Element | null {
    const { insightProps } = useValues(insightLogic)
    const { retentionFilter } = useValues(retentionLogic(insightProps))
    const { updateInsightFilter } = useActions(retentionLogic(insightProps))
    const quillSurface = useQuillSurface()
    const { minimumOccurrences = 1 } = retentionFilter || {}

    const onBlur = ({ target }: React.FocusEvent<HTMLInputElement>): void => {
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
    }

    if (quillSurface) {
        return (
            <QuillTooltip>
                <TooltipTrigger
                    render={
                        <Input
                            type="number"
                            className="w-20"
                            defaultValue={minimumOccurrences}
                            min={1}
                            onBlur={onBlur}
                        />
                    }
                />
                <TooltipContent className="max-w-64">{MINIMUM_OCCURRENCES_INFO}</TooltipContent>
            </QuillTooltip>
        )
    }

    return (
        <Tooltip title={<>{MINIMUM_OCCURRENCES_INFO}</>}>
            <LemonInput type="number" className="ml-2 w-20" defaultValue={minimumOccurrences} min={1} onBlur={onBlur} />
        </Tooltip>
    )
}
