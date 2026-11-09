import { Node } from '@xyflow/react'
import { useActions, useValues } from 'kea'

import { LemonBanner, LemonInput } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'
import { EmailTemplater } from 'scenes/hog-functions/email-templater/EmailTemplater'
import type { EmailTemplate } from 'scenes/hog-functions/email-templater/types'

import { sandboxSenderLogic } from '../../../../Channels/sandboxSenderLogic'
import { workflowLogic } from '../../../workflowLogic'
import { StepSchemaErrors } from '../components/StepSchemaErrors'
import { WorkflowAutoSaveIndicator } from '../components/WorkflowAutoSaveIndicator'
import { EmailSenderControl } from './EmailSenderControl'
import { SandboxEmailAction, sandboxRecipient, withSandboxEmail } from './emailStepVariants'

export function StepEmailSandboxConfiguration({ node }: { node: Node<SandboxEmailAction> }): JSX.Element {
    const { actionValidationErrorsById } = useValues(workflowLogic)
    const { setWorkflowAction } = useActions(workflowLogic)
    const { sandboxStatus, provisioning, provisionError } = useValues(sandboxSenderLogic)
    const { provisionSandboxSender } = useActions(sandboxSenderLogic)

    const action = node.data
    const email = action.config.inputs.email
    const emailErrors = actionValidationErrorsById[action.id]?.emailErrors
    const editEmail = (edit: Record<string, any>): void => setWorkflowAction(action.id, withSandboxEmail(action, edit))
    const fromLine = sandboxStatus?.from_address
        ? `${sandboxStatus.display_name} <${sandboxStatus.from_address}>`
        : null

    return (
        <>
            <StepSchemaErrors />
            <EmailSenderControl actionId={action.id} />
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
            <LemonField.Pure label="From">
                <span className="text-secondary truncate" translate="no" title={fromLine ?? undefined}>
                    {fromLine ?? 'Sandbox sender'}
                </span>
            </LemonField.Pure>
            <LemonField.Pure
                label="To"
                help="Only verified members of your organization receive sandbox email."
                error={emailErrors?.to}
            >
                <LemonInput
                    value={sandboxRecipient(action)}
                    onChange={(value) => editEmail({ to: { ...email.value.to, email: value } })}
                    placeholder="{{ person.properties.email }}"
                    data-attr="workflow-sandbox-email-to"
                />
            </LemonField.Pure>
            <EmailTemplater
                key={action.id}
                type="native_email_template"
                value={
                    {
                        ...email.value,
                        to: sandboxRecipient(action),
                        from: '',
                    } as Partial<EmailTemplate> as EmailTemplate
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
        </>
    )
}
