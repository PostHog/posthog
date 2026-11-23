import { useValues } from 'kea'
import { combineUrl } from 'kea-router'
import posthog from 'posthog-js'
import { useEffect } from 'react'

import { LemonBanner, LemonButton } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { captureEmailDomainSetupStarted, emailDomainSetupPath } from '../Channels/EmailDomain/emailDomainSetupLinks'
import { sandboxSenderLogic } from '../Channels/sandboxSenderLogic'
import { hasDeliverableSender, sandboxSenderAllowed } from './hogflows/steps/email/emailStepVariants'
import type { HogFlow } from './hogflows/types'
import {
    StoppedSenderSteps,
    changeSenderAdvice,
    repairTarget,
    stoppedSenderMessage,
    stoppedSenderSteps,
} from './stoppedSenderSteps'
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

    return broken && originalWorkflow ? (
        <StoppedSenderBanner {...props} broken={broken} live={originalWorkflow} />
    ) : null
}

function StoppedSenderBanner({
    broken,
    live,
    ...props
}: WorkflowLogicProps & { broken: StoppedSenderSteps; live: HogFlow }): JSX.Element {
    const { workflow, integrations, isViewOnly } = useValues(workflowLogic(props))
    const { canAdoptSandbox } = useValues(sandboxSenderLogic)
    const target = repairTarget(broken, live, workflow, integrations)
    const stepId = isViewOnly ? null : target.stepId
    const nextStep = changeSenderAdvice(
        broken.stepIds.length,
        !!hasDeliverableSender(integrations),
        canAdoptSandbox && sandboxSenderAllowed(live, !!props.editTemplateId) && target.testSenderTakesSteps
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
                <p className={stepId ? 'mb-2' : undefined}>{stoppedSenderMessage(broken, nextStep)}</p>
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
