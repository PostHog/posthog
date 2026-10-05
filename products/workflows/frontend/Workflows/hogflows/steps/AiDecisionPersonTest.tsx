import { useActions, useValues } from 'kea'

import { IconSparkles } from '@posthog/icons'

import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonProgress } from 'lib/lemon-ui/LemonProgress'

import { asDisplay } from 'products/persons/frontend/person-utils'

import { workflowLogic } from '../../workflowLogic'
import { getHogFlowBranchColor } from '../HogFlowBranchSelection'
import { hogFlowEditorTestLogic } from '../panel/testing/hogFlowEditorTestLogic'
import { AiDecisionConfig } from './aiDecisionBranches'
import { stepAiDecisionLogic } from './stepAiDecisionLogic'

export function AiDecisionPersonTest({ config }: { config: AiDecisionConfig }): JSX.Element {
    const { logicProps } = useValues(workflowLogic)
    const { sampleGlobals } = useValues(hogFlowEditorTestLogic(logicProps))
    const { personTestOutcome, personTestOutcomeLoading } = useValues(stepAiDecisionLogic)
    const { runPersonTest } = useActions(stepAiDecisionLogic)
    const personName = sampleGlobals?.person ? asDisplay(sampleGlobals.person) : 'The test person'

    return (
        <LemonField.Pure
            label="Test with a person"
            help="Asks the model about the person from the test event and shows every answer's probability and the path the person takes."
        >
            <div className="flex flex-col gap-2">
                <LemonButton
                    type="secondary"
                    icon={<IconSparkles />}
                    onClick={runPersonTest}
                    loading={personTestOutcomeLoading}
                    disabledReason={config.question.trim() ? undefined : 'Write a question first'}
                    tooltip="Runs the real model for this person and uses one AI decision from your AI credits."
                    data-attr="workflow-ai-decision-test-person"
                >
                    Test with a person
                </LemonButton>
                {personTestOutcome?.status === 'failed' && (
                    <LemonBanner type="error">{personTestOutcome.message}</LemonBanner>
                )}
                {personTestOutcome?.status === 'answered' && (
                    <div className="flex flex-col gap-2 rounded border p-3">
                        {personTestOutcome.answers.map((answer, index) => (
                            <div key={index} className="flex items-center gap-2 text-xs">
                                <span className={`w-24 shrink-0 truncate ${answer.chosen ? 'font-semibold' : ''}`}>
                                    {answer.label}
                                </span>
                                <LemonProgress
                                    className="flex-1"
                                    percent={answer.percent}
                                    strokeColor={answer.chosen ? getHogFlowBranchColor(index) : 'var(--color-border)'}
                                />
                                <span className="w-10 shrink-0 text-right tabular-nums">{`${answer.percent}%`}</span>
                            </div>
                        ))}
                        <div className="text-sm">
                            {`${personName} goes down the ${personTestOutcome.pathLabel} path.`}
                        </div>
                    </div>
                )}
            </div>
        </LemonField.Pure>
    )
}
