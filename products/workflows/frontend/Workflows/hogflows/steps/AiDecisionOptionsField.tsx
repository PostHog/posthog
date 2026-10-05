import { useActions, useValues } from 'kea'

import { IconPlus } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonTextArea } from 'lib/lemon-ui/LemonTextArea'

import { useHogFlowBranchSelection } from '../HogFlowBranchSelection'
import { AiDecisionConfig, MAX_AI_DECISION_OPTIONS, getAiDecisionOptions } from './aiDecisionBranches'
import { HogFlowBranchCard } from './HogFlowBranchCard'
import { stepAiDecisionLogic } from './stepAiDecisionLogic'

export function AiDecisionOptionsField({
    actionId,
    config,
}: {
    actionId: string
    config: AiDecisionConfig
}): JSX.Element {
    const { removeOptionDisabledReasons } = useValues(stepAiDecisionLogic)
    const { setOption, addOption, removeOption } = useActions(stepAiDecisionLogic)
    const { setSelectedBranch } = useHogFlowBranchSelection()
    const options = getAiDecisionOptions(config)

    return (
        <LemonField.Pure
            label={
                <span className="flex flex-1 items-center justify-between gap-2">
                    <span>Options</span>
                    <span className="text-xs font-normal text-secondary">{`${options.length} of ${MAX_AI_DECISION_OPTIONS}`}</span>
                </span>
            }
            help="Each option is a path out of this step. The model reads the descriptions, so say what sets each option apart."
        >
            <div className="flex flex-col gap-2">
                {options.map((option, index) => (
                    <HogFlowBranchCard
                        key={index}
                        actionId={actionId}
                        index={index}
                        name={option.name}
                        onNameChange={(name) => setOption(index, { name })}
                        placeholder={`Option ${index + 1}`}
                        ariaLabel={`Option ${index + 1} name`}
                        onRemove={() => {
                            setSelectedBranch(null)
                            removeOption(index)
                        }}
                        removeDisabledReason={removeOptionDisabledReasons[index]}
                    >
                        <LemonTextArea
                            value={option.description ?? ''}
                            onChange={(description) => setOption(index, { description })}
                            placeholder="Describe who belongs here"
                            minRows={1}
                        />
                    </HogFlowBranchCard>
                ))}
                <LemonButton
                    type="secondary"
                    icon={<IconPlus />}
                    onClick={addOption}
                    disabledReason={
                        options.length >= MAX_AI_DECISION_OPTIONS
                            ? `A question can have up to ${MAX_AI_DECISION_OPTIONS} options`
                            : undefined
                    }
                    data-attr="workflow-ai-decision-add-option"
                >
                    Add option
                </LemonButton>
            </div>
        </LemonField.Pure>
    )
}
