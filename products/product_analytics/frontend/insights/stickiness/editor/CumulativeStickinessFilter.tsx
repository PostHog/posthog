import { useActions, useValues } from 'kea'

import { LemonSelect } from '@posthog/lemon-ui'

import { useQuillSurface } from 'lib/components/QuillSurface/quillSurfaceContext'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

import { StickinessComputationMode, StickinessComputationModes } from '~/queries/schema/schema-general'
import { EditorFilterProps } from '~/types'

import { QuillEditorSelect } from 'products/product_analytics/frontend/insights/editor/QuillEditorSelect'

const COMPUTATION_MODE_OPTIONS = [
    {
        label: 'Non-cumulative',
        value: StickinessComputationModes.NonCumulative,
        tooltip: 'Show exact number of users active for each number of days',
    },
    {
        label: 'Cumulative',
        value: StickinessComputationModes.Cumulative,
        tooltip: 'Show number of users active for at least N days',
    },
]

export function CumulativeStickinessFilter({ insightProps }: EditorFilterProps): JSX.Element {
    const { stickinessFilter } = useValues(insightVizDataLogic(insightProps))
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))
    const quillSurface = useQuillSurface()

    const value = stickinessFilter?.computedAs || StickinessComputationModes.NonCumulative
    const onChange = (computedAs: StickinessComputationMode): void => {
        updateInsightFilter({ computedAs })
    }

    if (quillSurface) {
        return (
            <QuillEditorSelect
                className="w-48"
                data-attr="stickiness-mode-select"
                value={value}
                onChange={onChange}
                options={COMPUTATION_MODE_OPTIONS}
            />
        )
    }

    return (
        <LemonSelect
            className="w-48"
            data-attr="stickiness-mode-select"
            value={value}
            onChange={onChange}
            options={COMPUTATION_MODE_OPTIONS}
        />
    )
}
