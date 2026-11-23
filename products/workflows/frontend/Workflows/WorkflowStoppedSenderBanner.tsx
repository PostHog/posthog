import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import posthog from 'posthog-js'
import { useEffect } from 'react'

import { LemonBanner, LemonButton } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { captureEmailDomainSetupStarted, emailDomainSetupPath } from '../Channels/EmailDomain/emailDomainSetupLinks'
import { hogFlowEditorLogic } from './hogflows/hogFlowEditorLogic'
import { StoppedSenderSteps, stoppedSenderSteps } from './stoppedSenderSteps'
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

// Mounts the editor logic only while the banner shows, because a workflow on another tab has no canvas open.
function StoppedSenderBanner({ broken, ...props }: WorkflowLogicProps & { broken: StoppedSenderSteps }): JSX.Element {
    const { setSelectedNodeId } = useActions(hogFlowEditorLogic(props))
    const stepCount = broken.stepIds.length
    const steps = stepCount === 1 ? 'An email step' : `${stepCount} email steps`
    const those = stepCount === 1 ? 'that step' : 'those steps'

    return (
        <div className="shrink-0" data-attr="workflow-stopped-sender-banner">
            <LemonBanner
                type="error"
                action={{
                    children: 'Fix the domain',
                    'data-attr': 'workflow-stopped-sender-fix-domain',
                    to: emailDomainSetupPath(broken.senderId),
                    onClick: () => captureEmailDomainSetupStarted('stopped_sender_banner'),
                }}
            >
                <p className="mb-2">
                    Sending stopped for {broken.domains.join(', ')}. {steps} in this workflow can't send until the
                    domain's DNS records are fixed. Fix the domain, or change the sender on {those} to another sender or
                    the PostHog test sender.
                </p>
                <LemonButton
                    type="secondary"
                    size="small"
                    data-attr="workflow-stopped-sender-change-sender"
                    onClick={() => {
                        router.actions.push(urls.workflow(props.id ?? 'new', 'workflow'))
                        setSelectedNodeId(broken.stepIds[0])
                    }}
                >
                    Change the sender
                </LemonButton>
            </LemonBanner>
        </div>
    )
}
