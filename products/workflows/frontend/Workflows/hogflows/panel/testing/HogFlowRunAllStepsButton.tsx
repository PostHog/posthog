import { useActions, useValues } from 'kea'

import { IconPlay } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { workflowLogic } from '../../../workflowLogic'
import { HogflowTestInvocation, hogFlowEditorTestLogic } from './hogFlowEditorTestLogic'
import { testEmailRecipientLogic } from './testEmailRecipientLogic'

interface HogFlowRunAllStepsButtonProps {
    testInvocation: HogflowTestInvocation
    hasTestData: boolean
    isTestInvocationSubmitting: boolean
}

export function HogFlowRunAllStepsButton({
    testInvocation,
    hasTestData,
    isTestInvocationSubmitting,
}: HogFlowRunAllStepsButtonProps): JSX.Element | null {
    const { logicProps } = useValues(workflowLogic)
    const { testingV2Enabled } = useValues(testEmailRecipientLogic)
    const { runAllSteps } = useActions(hogFlowEditorTestLogic(logicProps))

    if (!testingV2Enabled) {
        return null
    }

    return (
        <LemonButton
            type="secondary"
            icon={<IconPlay />}
            data-attr="run-all-workflow-test-steps"
            onClick={() => runAllSteps(testInvocation)}
            disabledReason={
                !hasTestData
                    ? 'Load test data to run the steps'
                    : isTestInvocationSubmitting
                      ? 'Wait for the current test to finish'
                      : undefined
            }
            tooltip="Run every step from the trigger to the end. Emails, texts and push notifications are not sent in a full run. Test a message step on its own to send it."
            size="small"
        >
            Run all steps
        </LemonButton>
    )
}
