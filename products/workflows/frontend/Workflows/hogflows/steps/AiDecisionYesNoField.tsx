import { useActions } from 'kea'

import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonTextArea } from 'lib/lemon-ui/LemonTextArea'

import { AiDecisionConfig, getAiDecisionThresholds } from './aiDecisionBranches'
import { AiDecisionPercentSlider } from './AiDecisionPercentSlider'
import { stepAiDecisionLogic } from './stepAiDecisionLogic'

export function AiDecisionYesNoField({ config }: { config: AiDecisionConfig }): JSX.Element {
    const { updateConfig } = useActions(stepAiDecisionLogic)
    const { yesThreshold, noThreshold } = getAiDecisionThresholds(config)

    return (
        <LemonField.Pure
            label="When to answer yes"
            help={`The model gives the probability that the answer is yes. A person goes down the Yes path at ${yesThreshold}% or higher.`}
        >
            <div className="flex flex-col gap-2">
                <AiDecisionPercentSlider
                    value={yesThreshold}
                    min={config.unsure_enabled ? noThreshold + 1 : 1}
                    max={99}
                    onChange={(yes_threshold) => updateConfig({ yes_threshold })}
                />
                <LemonField.Pure label="What a yes means" showOptional>
                    <LemonTextArea
                        value={config.yes_means ?? ''}
                        onChange={(yes_means) => updateConfig({ yes_means })}
                        placeholder="The person works at a company and signed up with a work email"
                        minRows={1}
                        maxLength={500}
                    />
                </LemonField.Pure>
                <LemonField.Pure label="What a no means" showOptional>
                    <LemonTextArea
                        value={config.no_means ?? ''}
                        onChange={(no_means) => updateConfig({ no_means })}
                        placeholder="The person uses a personal email or is a student"
                        minRows={1}
                        maxLength={500}
                    />
                </LemonField.Pure>
            </div>
        </LemonField.Pure>
    )
}
