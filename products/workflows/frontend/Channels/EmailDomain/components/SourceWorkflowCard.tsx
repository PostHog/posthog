import { useValues } from 'kea'

import { LemonButton, LemonCard } from '@posthog/lemon-ui'

import { emailDomainSenderLogic } from '../emailDomainSenderLogic'
import { BigAction } from './BigAction'

/** The workflow the person opened the domain setup from. */
export interface SourceWorkflow {
    name: string
    /** True once the workflow is live or waiting for its domain. */
    enabled: boolean
    enableDisabledReason: string | null
    onEnable: () => void
    onBack: () => void
}

type SourceWorkflowStage = 'verifying' | 'ready'

const ENABLE_LABEL: Record<SourceWorkflowStage, string> = {
    verifying: 'Enable and send once verified',
    ready: 'Enable workflow',
}

function lead(workflow: SourceWorkflow, stage: SourceWorkflowStage, domain: string): string {
    if (workflow.enabled) {
        return stage === 'verifying' ? `It's on and starts sending once ${domain} is verified.` : "It's on."
    }
    if (workflow.enableDisabledReason) {
        return workflow.enableDisabledReason
    }
    return stage === 'verifying'
        ? `It starts sending once ${domain} is verified.`
        : `${domain} is verified. Turn the workflow on to start sending.`
}

/** Takes the person back to the workflow they came from, and offers to enable it, in place of the workflow suggestions. */
export function SourceWorkflowCard({
    workflow,
    stage,
}: {
    workflow: SourceWorkflow
    stage: SourceWorkflowStage
}): JSX.Element {
    const { domain } = useValues(emailDomainSenderLogic)
    const offersEnable = !workflow.enabled && !workflow.enableDisabledReason
    return (
        <LemonCard hoverEffect={false} className="rounded-xl @md:p-8 flex flex-col gap-5">
            <div className="flex flex-col gap-1 min-w-0">
                <span className="text-xs uppercase tracking-wide text-secondary">Your workflow</span>
                <h2 className="m-0 text-xl font-semibold break-words">{workflow.name}</h2>
                <p className="m-0 text-sm text-secondary break-words">
                    {lead(workflow, stage, domain ?? 'the domain')}
                </p>
            </div>
            <div className="flex flex-col gap-2">
                {offersEnable && (
                    <BigAction onClick={workflow.onEnable} data-attr="email-domain-workflow-enable">
                        {ENABLE_LABEL[stage]}
                    </BigAction>
                )}
                <LemonButton
                    type={offersEnable ? 'tertiary' : 'secondary'}
                    size="large"
                    fullWidth
                    center
                    onClick={workflow.onBack}
                    data-attr="email-domain-workflow-back"
                >
                    Back to workflow
                </LemonButton>
            </div>
        </LemonCard>
    )
}
