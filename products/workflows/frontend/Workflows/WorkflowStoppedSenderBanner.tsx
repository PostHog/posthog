import { useValues } from 'kea'
import { combineUrl } from 'kea-router'
import posthog from 'posthog-js'
import { useEffect } from 'react'

import { LemonBanner, LemonButton } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { captureEmailDomainSetupStarted, emailDomainSetupPath } from '../Channels/EmailDomain/emailDomainSetupLinks'
import { StoppedSenderSteps, stepToChange, stoppedSenderMessage, stoppedSenderSteps } from './stoppedSenderSteps'
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
    const { workflow, integrations, isViewOnly } = useValues(workflowLogic(props))
    const stepId = isViewOnly ? null : stepToChange(broken, workflow, integrations)

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
                <p className={stepId ? 'mb-2' : undefined}>{stoppedSenderMessage(broken)}</p>
                {stepId && (
                    <LemonButton
                        type="secondary"
                        size="small"
                        className="w-fit"
                        data-attr="workflow-stopped-sender-change-sender"
                        // The editor reads the step and mode from the URL when it mounts, so this works from any tab.
                        to={
                            combineUrl(urls.workflow(props.id ?? 'new', 'workflow'), {
                                node: stepId,
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
