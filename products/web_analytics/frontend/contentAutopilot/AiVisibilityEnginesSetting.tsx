import { useActions, useValues } from 'kea'

import type { AEOEngineSettingApi, CheckFrequencyEnumApi } from 'products/web_analytics/frontend/generated/api.schemas'

import { AiVisibilityBanner } from './AiVisibilityBanner'
import { aiVisibilityEnginesLogic } from './aiVisibilityEnginesLogic'
import { AiVisibilityEnginesTable } from './AiVisibilityEnginesTable'
import { unavailableEngineReason } from './utils'

const FREQUENCY_OPTIONS: { value: CheckFrequencyEnumApi; label: string }[] = [
    { value: 'daily', label: 'Every day' },
    { value: 'weekly', label: 'Once a week' },
]
const FREQUENCY_TOOLTIP =
    'Once a week checks a seventh of your prompts each day, so every prompt gets one check a week.'
const NO_SEARCH_NOTE =
    'Answers from what the model already knows, without searching the web. It never cites pages, so compare its mention rate.'

/** Which answer engines check the project's prompts, and how often. Each engine gets its own column in the reports. */
export const AiVisibilityEnginesSetting = (): JSX.Element => {
    const { engines, enginesLoading, enginesError, updatingEngines } = useValues(aiVisibilityEnginesLogic)
    const { updateEngine, loadEngines } = useActions(aiVisibilityEnginesLogic)
    const disabledReason = (setting: AEOEngineSettingApi): string | undefined =>
        unavailableEngineReason(setting) ?? (updatingEngines.includes(setting.engine) ? 'Saving…' : undefined)

    return (
        <div className="flex flex-col gap-3" data-attr="ai-visibility-engines-setting">
            {enginesError ? (
                <AiVisibilityBanner
                    type="error"
                    action={{ children: 'Try again', onClick: loadEngines, loading: enginesLoading }}
                >
                    Couldn't load the engines. Try again, and if it keeps happening contact support.
                </AiVisibilityBanner>
            ) : null}
            <AiVisibilityEnginesTable
                engines={enginesError ? [] : (engines ?? [])}
                loading={enginesLoading}
                frequencyOptions={FREQUENCY_OPTIONS}
                frequencyTooltip={FREQUENCY_TOOLTIP}
                noSearchNote={NO_SEARCH_NOTE}
                disabledReason={disabledReason}
                onChange={updateEngine}
            />
        </div>
    )
}
