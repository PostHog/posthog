import { Node } from '@xyflow/react'
import { useActions, useValues } from 'kea'

import { LemonBanner } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'
import { EmailTemplater } from 'scenes/hog-functions/email-templater/EmailTemplater'
import type { EmailTemplate } from 'scenes/hog-functions/email-templater/types'

import { sandboxSenderLogic } from '../../../../Channels/sandboxSenderLogic'
import { workflowLogic } from '../../../workflowLogic'
import { hogFlowEditorTestLogic } from '../../panel/testing/hogFlowEditorTestLogic'
import { buildSampleGlobals } from '../components/HogFlowFunctionConfiguration'
import { StepSchemaErrors } from '../components/StepSchemaErrors'
import { WorkflowAutoSaveIndicator } from '../components/WorkflowAutoSaveIndicator'
import { emailSenderControlLogic } from './emailSenderControlLogic'
import { SandboxEmailAction, withSandboxEmail } from './emailStepVariants'
import { SandboxSenderChoiceProvider } from './SandboxSenderChoiceProvider'

export function StepEmailSandboxConfiguration({ node }: { node: Node<SandboxEmailAction> }): JSX.Element {
    const { actionValidationErrorsById, logicProps, workflow } = useValues(workflowLogic)
    const { sampleGlobals: realSampleGlobals } = useValues(hogFlowEditorTestLogic(logicProps))
    const { setWorkflowAction } = useActions(workflowLogic)
    const { provisioning, provisionError, sandboxSetup } = useValues(sandboxSenderLogic)
    const { provisionSandboxSender } = useActions(sandboxSenderLogic)
    const action = node.data
    const { chooseSender } = useActions(
        emailSenderControlLogic({ workflowLogicProps: logicProps, actionId: action.id })
    )

    const email = action.config.inputs.email
    const emailErrors = actionValidationErrorsById[action.id]?.emailErrors
    const editEmail = (edit: Record<string, any>): void => {
        const integrationId = edit.from?.integrationId
        if (typeof integrationId === 'number') {
            chooseSender(integrationId)
            return
        }
        setWorkflowAction(action.id, withSandboxEmail(action, edit))
    }

    return (
        <>
            <StepSchemaErrors />
            {sandboxSetup && (
                <LemonBanner
                    type={provisionError ? 'error' : 'warning'}
                    action={
                        sandboxSetup.canSetUp
                            ? {
                                  children: provisionError ? 'Try again' : 'Set up the sandbox sender',
                                  loading: provisioning,
                                  onClick: () => provisionSandboxSender('sender_control'),
                              }
                            : undefined
                    }
                >
                    {sandboxSetup.problem}
                </LemonBanner>
            )}
            <SandboxSenderChoiceProvider actionId={action.id}>
                <LemonField.Pure label="Email message">
                    <EmailTemplater
                        key={action.id}
                        type="native_email_sandbox"
                        variables={buildSampleGlobals(workflow.trigger, workflow.variables, realSampleGlobals)}
                        value={
                            {
                                ...email.value,
                                to: { email: '', ...email.value.to },
                                from: {},
                            } as unknown as EmailTemplate
                        }
                        onChange={editEmail}
                        templating={email.templating}
                        onChangeTemplating={(templating) =>
                            setWorkflowAction(action.id, {
                                ...action,
                                config: { ...action.config, inputs: { email: { ...email, templating } } },
                            })
                        }
                        liveChanges
                        saveIndicator={<WorkflowAutoSaveIndicator />}
                        fieldErrors={emailErrors}
                    />
                </LemonField.Pure>
            </SandboxSenderChoiceProvider>
        </>
    )
}
