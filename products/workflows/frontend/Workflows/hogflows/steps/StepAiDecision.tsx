import { Node } from '@xyflow/react'
import { BindLogic, useActions, useValues } from 'kea'

import { IconSparkles } from '@posthog/icons'

import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonSegmentedButton, LemonSegmentedButtonOption } from 'lib/lemon-ui/LemonSegmentedButton'
import { LemonTextArea } from 'lib/lemon-ui/LemonTextArea'

import { workflowLogic } from '../../workflowLogic'
import { AiDecisionAction, AiDecisionAnswerType } from './aiDecisionBranches'
import { AiDecisionContextField } from './AiDecisionContextField'
import { AiDecisionOptionsField } from './AiDecisionOptionsField'
import { AiDecisionPersonTest } from './AiDecisionPersonTest'
import { AiDecisionUnsureField } from './AiDecisionUnsureField'
import { AiDecisionYesNoField } from './AiDecisionYesNoField'
import { StepSchemaErrors } from './components/StepSchemaErrors'
import { stepAiDecisionLogic } from './stepAiDecisionLogic'

export function StepAiDecisionConfiguration({ node }: { node: Node<AiDecisionAction> }): JSX.Element {
    const { logicProps } = useValues(workflowLogic)

    return (
        <BindLogic logic={stepAiDecisionLogic} props={{ workflowLogicProps: logicProps, actionId: node.id }}>
            <StepAiDecisionFields action={node.data} />
        </BindLogic>
    )
}

function StepAiDecisionFields({ action }: { action: AiDecisionAction }): JSX.Element {
    const { answerTypeDisabledReason } = useValues(stepAiDecisionLogic)
    const { updateConfig, setAnswerType } = useActions(stepAiDecisionLogic)
    const config = action.config
    const answerTypeOption = (
        value: AiDecisionAnswerType,
        label: string
    ): LemonSegmentedButtonOption<AiDecisionAnswerType> => ({
        value,
        label,
        disabledReason: config.answer_type === value ? undefined : answerTypeDisabledReason,
    })

    return (
        <div className="flex flex-col gap-4">
            <StepSchemaErrors />
            <LemonField.Pure
                label="Question"
                help="Every person gets this question as written. Person and event data go under What the model sees."
            >
                <LemonTextArea
                    value={config.question}
                    onChange={(question) => updateConfig({ question })}
                    placeholder="Which onboarding track fits this person best?"
                    minRows={2}
                    data-attr="workflow-ai-decision-question"
                />
            </LemonField.Pure>

            <LemonField.Pure label="Answer">
                <LemonSegmentedButton<AiDecisionAnswerType>
                    fullWidth
                    size="small"
                    value={config.answer_type}
                    onChange={setAnswerType}
                    options={[answerTypeOption('yes_no', 'Yes or no'), answerTypeOption('pick_one', 'Pick one')]}
                />
            </LemonField.Pure>

            {config.answer_type === 'pick_one' ? (
                <AiDecisionOptionsField actionId={action.id} config={config} />
            ) : (
                <AiDecisionYesNoField config={config} />
            )}
            <AiDecisionUnsureField config={config} />
            <AiDecisionContextField config={config} />

            <div className="flex gap-2 rounded border border-dashed p-2 text-xs text-secondary">
                <IconSparkles className="text-base shrink-0" />
                <span>Each person who reaches this step uses one AI decision from your AI credits.</span>
            </div>

            <LemonDivider className="my-0" />
            <AiDecisionPersonTest config={config} />
        </div>
    )
}
