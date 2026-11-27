import { useActions, useValues } from 'kea'

import type { AEOEngineSettingApi } from 'products/web_analytics/frontend/generated/api.schemas'

import { AiVisibilityBanner } from './AiVisibilityBanner'
import { aiVisibilityEnginesLogic } from './aiVisibilityEnginesLogic'
import { AiVisibilityEnginesTable } from './AiVisibilityEnginesTable'
import { FREQUENCY_OPTIONS } from './engineFrequency'
import { unavailableEngineReason } from './utils'

const FREQUENCY_TOOLTIP =
    'Every 72 hours checks a third of your prompts each day, and weekly a seventh, so every prompt gets one check per period.'
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
