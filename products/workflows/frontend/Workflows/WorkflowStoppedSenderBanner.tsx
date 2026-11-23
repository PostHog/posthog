import { useValues } from 'kea'
import { combineUrl } from 'kea-router'
import posthog from 'posthog-js'
import { useEffect } from 'react'

import { LemonBanner, LemonButton } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { captureEmailDomainSetupStarted, emailDomainSetupPath } from '../Channels/EmailDomain/emailDomainSetupLinks'
import { sandboxSenderLogic } from '../Channels/sandboxSenderLogic'
import {
    hasDeliverableSender,
    sandboxSenderAllowed,
    sandboxTakesStepId,
} from './hogflows/steps/email/emailStepVariants'
import { StoppedSenderSteps, changeSenderAdvice, stoppedSenderSteps } from './stoppedSenderSteps'
import { WorkflowLogicProps, workflowLogic } from './workflowLogic'

export function WorkflowStoppedSenderBanner(props: WorkflowLogicProps): JSX.Element | null {
    const { originalWorkflow, integrations } = useValues(workflowLogic(props))
    const broken = stoppedSenderSteps(originalWorkflow, integrations)
    const stepCount = broken?.stepIds.length ?? 0

    useEffect(() => {
        if (stepCount > 0) {
            // pinned: analytics event name and properties
            posthog.capture('workflows stopped sender banner shown', { workflow_id: props.id, step_count: stepCount })
        }
    }, [stepCount, props.id])

    return broken ? <StoppedSenderBanner {...props} broken={broken} /> : null
}

function StoppedSenderBanner({ broken, ...props }: WorkflowLogicProps & { broken: StoppedSenderSteps }): JSX.Element {
    const { originalWorkflow, workflow, integrations, isViewOnly } = useValues(workflowLogic(props))
    const { canAdoptSandbox } = useValues(sandboxSenderLogic)
    const stepCount = broken.stepIds.length
    const steps = stepCount === 1 ? 'An email step' : `${stepCount} email steps`
    const domains = broken.domains.length === 1 ? "the domain's" : "the domains'"
    // Unsaved edits can delete a broken step, so the button opens one the editor still has.
    const stepToChange = broken.stepIds.find((id) => workflow.actions.some((action) => action.id === id))
    const nextStep = changeSenderAdvice(
        stepCount,
        !!hasDeliverableSender(integrations),
        canAdoptSandbox &&
            !!originalWorkflow &&
            sandboxSenderAllowed(originalWorkflow, !!props.editTemplateId) &&
            broken.stepIds.every((id) => sandboxTakesStepId({ id }))
    )

    return (
        <div className="shrink-0" data-attr="workflow-stopped-sender-banner">
            <LemonBanner
                type="error"
                action={{
                    children: 'Fix your sending domain',
                    'data-attr': 'workflow-stopped-sender-fix-domain',
                    to: emailDomainSetupPath(broken.senderId),
                    onClick: () => captureEmailDomainSetupStarted('stopped_sender_banner'),
                }}
            >
                <p className={stepToChange && !isViewOnly ? 'mb-2' : undefined}>
                    Sending stopped for {broken.domains.join(', ')}. {steps} in this workflow can't send until {domains}{' '}
                    DNS records are fixed. Fix your sending domain, or {nextStep}.
                </p>
                {stepToChange && !isViewOnly && (
                    <LemonButton
                        type="secondary"
                        size="small"
                        data-attr="workflow-stopped-sender-change-sender"
                        // The editor reads the step and mode from the URL when it mounts, so this works from any tab.
                        to={
                            combineUrl(urls.workflow(props.id ?? 'new', 'workflow'), {
                                node: stepToChange,
                                mode: 'build',
                            }).url
                        }
                    >
                        Change the sender
                    </LemonButton>
                )}
            </LemonBanner>
        </div>
    )
}
