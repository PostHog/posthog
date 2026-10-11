import { useActions, useValues } from 'kea'

import { IconSparkles, IconWarning } from '@posthog/icons'
import { LemonButton, LemonCard, LemonDialog, LemonInput, LemonTag, LemonTextArea } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

import type { WorkflowIdeaApi } from '../../generated/api.schemas'
import { ideaEmails } from './ideaCopy'
import { IdeaLinkStep } from './IdeaLinkStep'
import { IdeaSenderStep } from './IdeaSenderStep'
import { WorkflowIdeaEmailPreview } from './WorkflowIdeaEmailPreview'
import { WorkflowIdeaFacts } from './WorkflowIdeaFacts'
import { WorkflowIdeaImpact } from './WorkflowIdeaImpact'
import { workflowIdeasLogic } from './workflowIdeasLogic'

const TIER_LABEL: Record<string, string> = {
    revenue: 'Revenue',
    activation: 'Activation',
    retention: 'Retention',
    engagement: 'Engagement',
}

/** A workflow PostHog drafted for the project, with what it does, what it is worth and the steps to use it. */
export function WorkflowIdeaCard({
    idea,
    recommended = false,
}: {
    idea: WorkflowIdeaApi
    recommended?: boolean
}): JSX.Element {
    const { busyId, emailSender, siteInput, enteredSite } = useValues(workflowIdeasLogic)
    const { applyIdea, dismissIdea, setSiteInput } = useActions(workflowIdeasLogic)
    const busy = busyId === idea.id
    const { evidence } = idea
    const emails = ideaEmails(idea.definition)
    const needsSender = emailSender.status === 'none' || emailSender.status === 'unverified'

    const openPreview = (): void => {
        LemonDialog.open({
            title: idea.title,
            width: 680,
            content: <WorkflowIdeaEmailPreview emails={emails} waits={evidence.waits ?? []} />,
            primaryButton: { children: 'Close' },
        })
    }

    const openDismiss = (): void => {
        LemonDialog.openForm({
            title: 'Dismiss this idea?',
            description: "PostHog won't suggest it again in this project.",
            initialValues: { reason: '' },
            content: (
                <LemonField name="reason" label="Why not? (optional)">
                    <LemonTextArea
                        placeholder="For example: we already send this from our own app"
                        maxLength={2000}
                        // The dialog form submits on Enter, which would dismiss before the reason is finished.
                        onKeyDown={(e) => e.key === 'Enter' && e.stopPropagation()}
                        data-attr="workflow-idea-dismiss-reason"
                    />
                </LemonField>
            ),
            primaryButtonProps: { children: 'Dismiss' },
            onSubmit: ({ reason }) => dismissIdea(idea, reason ?? ''),
        })
    }

    return (
        <LemonCard hoverEffect={false} className="flex h-full flex-col gap-3 p-4" data-attr="workflow-idea">
            <div className="flex flex-wrap items-center gap-2">
                <LemonTag type="highlight" icon={<IconSparkles />}>
                    Drafted by PostHog
                </LemonTag>
                <LemonTag type="muted">{TIER_LABEL[idea.value_tier] ?? idea.value_tier}</LemonTag>
                {recommended && <LemonTag type="success">Start here</LemonTag>}
            </div>
            <div className="flex flex-col gap-1">
                <h4 className="mb-0 text-base font-semibold">{idea.title}</h4>
                <p className="mb-0 text-sm text-secondary">{idea.rationale}</p>
            </div>
            <WorkflowIdeaFacts evidence={evidence} emailCount={emails.length} />
            <WorkflowIdeaImpact evidence={evidence} />
            {evidence.review_note && (
                <div className="flex items-start gap-2 rounded border border-warning p-2 text-xs">
                    <IconWarning className="mt-0.5 shrink-0 text-warning" />
                    <span>{evidence.review_note}</span>
                </div>
            )}
            {evidence.site_url ? null : (
                <LemonField.Pure
                    label="Your website"
                    help="The email buttons link here. You can point each one at an exact page later."
                >
                    <LemonInput
                        size="small"
                        placeholder="example.com"
                        value={siteInput}
                        onChange={setSiteInput}
                        data-attr="workflow-idea-site-input"
                    />
                </LemonField.Pure>
            )}
            <ul className="m-0 flex list-none flex-col gap-1 p-0 text-xs text-secondary">
                {evidence.site_url && <IdeaLinkStep siteUrl={evidence.site_url} />}
                {needsSender && <IdeaSenderStep sender={emailSender} />}
            </ul>
            <div className="mt-auto flex flex-wrap gap-2">
                <LemonButton
                    type="primary"
                    size="small"
                    loading={busy}
                    disabledReason={
                        busyId && !busy
                            ? 'Another idea is being saved'
                            : !evidence.site_url && !enteredSite
                              ? 'Add your website so the email buttons link somewhere'
                              : undefined
                    }
                    onClick={() => applyIdea(idea)}
                    // pinned: data-attr - autocapture dashboards read it
                    data-attr="workflow-idea-use"
                >
                    Use this workflow
                </LemonButton>
                <LemonButton
                    type="secondary"
                    size="small"
                    onClick={openPreview}
                    // pinned: data-attr - autocapture dashboards read it
                    data-attr="workflow-idea-preview-open"
                >
                    Preview emails
                </LemonButton>
                <LemonButton
                    type="tertiary"
                    size="small"
                    disabledReason={busyId ? 'An idea is being saved' : undefined}
                    onClick={openDismiss}
                    // pinned: data-attr - autocapture dashboards read it
                    data-attr="workflow-idea-dismiss"
                >
                    Dismiss
                </LemonButton>
            </div>
        </LemonCard>
    )
}
