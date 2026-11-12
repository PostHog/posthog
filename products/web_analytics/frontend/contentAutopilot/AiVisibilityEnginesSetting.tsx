import { useActions, useValues } from 'kea'

import { LemonBanner, LemonSelect, LemonSwitch, LemonTable } from '@posthog/lemon-ui'

import type { AEOEngineSettingApi, CheckFrequencyEnumApi } from 'products/web_analytics/frontend/generated/api.schemas'

import { aiVisibilityEnginesLogic } from './aiVisibilityEnginesLogic'
import { engineLabel } from './utils'

const FREQUENCY_OPTIONS: { value: CheckFrequencyEnumApi; label: string }[] = [
    { value: 'daily', label: 'Every day' },
    { value: 'weekly', label: 'Once a week' },
]

const unavailableReason = (setting: AEOEngineSettingApi): string | undefined =>
    setting.available ? undefined : "This engine isn't set up for this project yet."

/** Which answer engines check the project's prompts, and how often. Each engine gets its own column in the reports. */
export const AiVisibilityEnginesSetting = (): JSX.Element => {
    const { engines, enginesLoading, enginesError, updatingEngines } = useValues(aiVisibilityEnginesLogic)
    const { updateEngine, loadEngines } = useActions(aiVisibilityEnginesLogic)

    return (
        <div className="flex flex-col gap-3" data-attr="ai-visibility-engines-setting">
            {enginesError ? (
                <LemonBanner
                    type="error"
                    action={{ children: 'Try again', onClick: loadEngines, loading: enginesLoading }}
                >
                    Couldn't load the engines. Try again, and if it keeps happening contact support.
                </LemonBanner>
            ) : null}
            <LemonTable<AEOEngineSettingApi>
                size="small"
                dataSource={enginesError ? [] : (engines ?? [])}
                loading={enginesLoading}
                rowKey="engine"
                columns={[
                    {
                        title: 'Engine',
                        key: 'engine',
                        render: (_, setting) => (
                            <div className="flex flex-col">
                                <span className="font-semibold">{engineLabel(setting.engine)}</span>
                                {setting.mode === 'no_search' ? (
                                    <span className="text-xs text-muted">
                                        Answers from what the model already knows, without searching the web. It never
                                        cites pages, so compare its mention rate.
                                    </span>
                                ) : null}
                            </div>
                        ),
                    },
                    {
                        title: 'Checks prompts',
                        key: 'enabled',
                        width: 0,
                        render: (_, setting) => (
                            <LemonSwitch
                                checked={setting.enabled && setting.available}
                                onChange={(enabled) => updateEngine(setting.engine, { enabled })}
                                disabledReason={
                                    unavailableReason(setting) ??
                                    (updatingEngines.includes(setting.engine) ? 'Saving…' : undefined)
                                }
                                data-attr="ai-visibility-engine-enabled"
                            />
                        ),
                    },
                    {
                        title: 'How often',
                        key: 'frequency',
                        tooltip:
                            'Once a week checks a seventh of your prompts each day, so every prompt gets one check a week.',
                        render: (_, setting) => (
                            <LemonSelect
                                size="small"
                                className="min-w-36"
                                value={setting.frequency}
                                options={FREQUENCY_OPTIONS}
                                onSelect={(frequency) => frequency && updateEngine(setting.engine, { frequency })}
                                disabledReason={
                                    unavailableReason(setting) ??
                                    (updatingEngines.includes(setting.engine) ? 'Saving…' : undefined)
                                }
                                data-attr="ai-visibility-engine-frequency"
                            />
                        ),
                    },
                ]}
            />
        </div>
    )
}
