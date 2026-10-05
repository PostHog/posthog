import { useActions, useValues } from 'kea'

import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonSwitch } from 'lib/lemon-ui/LemonSwitch'

import { AiDecisionConfig, getAiDecisionThresholds } from './aiDecisionBranches'
import { AiDecisionPercentSlider } from './AiDecisionPercentSlider'
import { stepAiDecisionLogic } from './stepAiDecisionLogic'

function getUnsureHelp(config: AiDecisionConfig): string {
    const { yesThreshold, noThreshold, minPickProbability } = getAiDecisionThresholds(config)
    if (!config.unsure_enabled) {
        return "Sends the answers the model isn't sure about down their own path, for example to a person who reviews them."
    }
    if (config.answer_type === 'pick_one') {
        return `A person goes down the Unsure path when no option reaches ${minPickProbability}%.`
    }
    return `A person goes down the No path at ${noThreshold}% or lower, and down the Unsure path between ${noThreshold}% and ${yesThreshold}%.`
}

export function AiDecisionUnsureField({ config }: { config: AiDecisionConfig }): JSX.Element {
    const { unsureOffDisabledReason } = useValues(stepAiDecisionLogic)
    const { setUnsureEnabled, updateConfig } = useActions(stepAiDecisionLogic)
    const { yesThreshold, noThreshold, minPickProbability } = getAiDecisionThresholds(config)

    return (
        <LemonField.Pure label="When the model is unsure" help={getUnsureHelp(config)}>
            <div className="flex flex-col gap-2">
                <LemonSwitch
                    bordered
                    fullWidth
                    label="Add an Unsure path"
                    checked={!!config.unsure_enabled}
                    onChange={setUnsureEnabled}
                    disabledReason={unsureOffDisabledReason}
                    data-attr="workflow-ai-decision-unsure"
                />
                {config.unsure_enabled &&
                    (config.answer_type === 'pick_one' ? (
                        <AiDecisionPercentSlider
                            value={minPickProbability}
                            min={1}
                            max={99}
                            onChange={(min_pick_probability) => updateConfig({ min_pick_probability })}
                        />
                    ) : (
                        <AiDecisionPercentSlider
                            value={noThreshold}
                            min={1}
                            max={Math.min(98, yesThreshold - 1)}
                            onChange={(no_threshold) => updateConfig({ no_threshold })}
                        />
                    ))}
            </div>
        </LemonField.Pure>
    )
}
