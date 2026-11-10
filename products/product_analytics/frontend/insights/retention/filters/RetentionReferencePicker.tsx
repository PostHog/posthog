import { useActions, useValues } from 'kea'

import { LemonSelect } from '@posthog/lemon-ui'

import { useQuillSurface } from 'lib/components/QuillSurface/quillSurfaceContext'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

import { RetentionFilter } from '~/queries/schema/schema-general'

import { QuillEditorSelect } from 'products/product_analytics/frontend/insights/editor/QuillEditorSelect'

type RetentionReference = NonNullable<RetentionFilter['retentionReference']>

const REFERENCE_OPTIONS: { value: RetentionReference; label: string; tooltip: string }[] = [
    {
        value: 'total',
        label: 'starting cohort size',
        tooltip:
            'eg. Retention for day 3 will be percentage of users who returned on day 3 as a percentage of users on day 0 (users who preformed start event)',
    },
    {
        value: 'previous',
        label: 'previous period',
        tooltip:
            'eg. Retention for day 3 will be percentage of users who returned on day 3 as a percentage of users who returned on day 2 (the previous period)',
    },
]

export function RetentionReferencePicker(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { retentionFilter } = useValues(insightVizDataLogic(insightProps))
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))
    const quillSurface = useQuillSurface()

    const { retentionReference } = retentionFilter || {}
    const onChange = (retentionReference: RetentionReference): void => {
        updateInsightFilter({ retentionReference })
    }

    if (quillSurface) {
        return (
            <QuillEditorSelect
                className="w-60"
                value={retentionReference || 'total'}
                onChange={onChange}
                options={REFERENCE_OPTIONS}
            />
        )
    }

    return (
        <LemonSelect
            className="w-60"
            size="small"
            value={retentionReference || 'total'}
            onChange={onChange}
            options={REFERENCE_OPTIONS}
        />
    )
}
