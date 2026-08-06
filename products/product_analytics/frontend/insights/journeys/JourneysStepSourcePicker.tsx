import { useActions, useValues } from 'kea'

import { LemonSegmentedButton } from 'lib/lemon-ui/LemonSegmentedButton'

import { EditorFilterProps } from '~/types'

import { journeysDataLogic } from './journeysDataLogic'
import { STEP_SOURCE_PRESETS, StepSourcePreset, presetForStepSources } from './stepSourcePresets'

const PRESET_OPTIONS = Object.values(STEP_SOURCE_PRESETS).map(({ key, label }) => ({
    value: key,
    label,
    'data-attr': `journeys-step-source-${key}`,
}))

export function JourneysStepSourcePicker({ insightProps }: EditorFilterProps): JSX.Element {
    const { pathsV2Filter } = useValues(journeysDataLogic(insightProps))
    const { updateInsightFilter } = useActions(journeysDataLogic(insightProps))

    const preset = presetForStepSources(pathsV2Filter?.stepSources ?? undefined)

    return (
        <LemonSegmentedButton
            size="small"
            value={preset?.key}
            onChange={(key: StepSourcePreset['key']) =>
                updateInsightFilter({ stepSources: STEP_SOURCE_PRESETS[key].stepSources })
            }
            options={PRESET_OPTIONS}
        />
    )
}
