import { Node } from '@xyflow/react'
import { useActions, useValues } from 'kea'

import { LemonBanner } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'
import { EmailTemplater } from 'scenes/hog-functions/email-templater/EmailTemplater'
import type { EmailTemplate } from 'scenes/hog-functions/email-templater/types'

import { sandboxSenderLogic } from '../../../../Channels/sandboxSenderLogic'
import { workflowLogic } from '../../../workflowLogic'
import { StepSchemaErrors } from '../components/StepSchemaErrors'
import { WorkflowAutoSaveIndicator } from '../components/WorkflowAutoSaveIndicator'
import { emailSenderControlLogic } from './emailSenderControlLogic'
import { SandboxEmailAction, withSandboxEmail } from './emailStepVariants'
import { SandboxSenderChoiceProvider } from './SandboxSenderChoiceProvider'

export function StepEmailSandboxConfiguration({ node }: { node: Node<SandboxEmailAction> }): JSX.Element {
    const { actionValidationErrorsById, logicProps } = useValues(workflowLogic)
    const { setWorkflowAction } = useActions(workflowLogic)
    const { provisioning, provisionError } = useValues(sandboxSenderLogic)
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
            {provisionError && (
                <LemonBanner
                    type="error"
                    action={{
                        children: 'Try again',
                        loading: provisioning,
                        onClick: () => provisionSandboxSender('sender_control'),
                    }}
                >
                    {provisionError}
                </LemonBanner>
            )}
            <SandboxSenderChoiceProvider actionId={action.id}>
                <LemonField.Pure label="Email message">
                    <EmailTemplater
                        key={action.id}
                        type="native_email_sandbox"
                        value={
                            // Like an own step's input, this form keeps To as { email, name } rather than the type's string.
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
