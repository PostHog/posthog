import { useActions, useValues } from 'kea'

import { useQuillSurface } from 'lib/components/QuillSurface/quillSurfaceContext'
import { LemonSelect } from 'lib/lemon-ui/LemonSelect'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

import { RetentionFilter } from '~/queries/schema/schema-general'

import { QuillEditorSelect } from 'products/product_analytics/frontend/insights/editor/QuillEditorSelect'

import { RETENTION_TIME_WINDOW_MODE_OPTIONS } from '../constants'

export function RetentionTimeWindowModePicker(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { retentionFilter } = useValues(insightVizDataLogic(insightProps))
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))
    const quillSurface = useQuillSurface()

    const handleChange = (timeWindowMode?: RetentionFilter['timeWindowMode']): void => {
        updateInsightFilter({ timeWindowMode })
    }

    if (quillSurface) {
        return (
            <QuillEditorSelect
                value={retentionFilter?.timeWindowMode ?? 'strict_calendar_dates'}
                onChange={handleChange}
                options={RETENTION_TIME_WINDOW_MODE_OPTIONS}
            />
        )
    }

    return (
        <LemonSelect
            value={retentionFilter?.timeWindowMode ?? 'strict_calendar_dates'}
            onChange={handleChange}
            options={RETENTION_TIME_WINDOW_MODE_OPTIONS}
            dropdownMatchSelectWidth={false}
        />
    )
}
