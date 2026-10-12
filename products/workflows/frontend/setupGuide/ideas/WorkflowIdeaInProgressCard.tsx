import { useValues } from 'kea'

import { IconCheckCircle, IconClock, IconLetter, IconWarning } from '@posthog/icons'
import { LemonButton, LemonCard, LemonTag } from '@posthog/lemon-ui'

import { humanFriendlyNumber } from 'lib/utils/numbers'
import { pluralize } from 'lib/utils/strings'
import { urls } from 'scenes/urls'

import type { WorkflowIdeaApi } from '../../generated/api.schemas'
import { ideaEmails } from './ideaCopy'
import { IdeaLinkStep } from './IdeaLinkStep'
import { IdeaSenderActions } from './IdeaSenderActions'
import { IdeaSenderStep } from './IdeaSenderStep'
import { workflowIdeasLogic } from './workflowIdeasLogic'

/** A used idea whose workflow is still a draft: what is done, what is left, and what waiting is costing. */
export function WorkflowIdeaInProgressCard({
    idea,
    hogFlowId,
}: {
    idea: WorkflowIdeaApi
    hogFlowId: string
}): JSX.Element {
    const { emailSender } = useValues(workflowIdeasLogic)
    const { evidence } = idea
    const needsSender = emailSender.status === 'none' || emailSender.status === 'unverified'

    return (
        <LemonCard hoverEffect={false} className="flex h-full flex-col gap-3 p-4" data-attr="workflow-idea-in-progress">
            <div className="flex flex-wrap items-center gap-2">
                <LemonTag type="completion">In progress</LemonTag>
            </div>
            <h4 className="mb-0 text-base font-semibold">{idea.title}</h4>
            <ol className="m-0 flex list-none flex-col gap-2 p-0 text-sm">
                <li className="flex items-start gap-2">
                    <IconCheckCircle className="mt-0.5 shrink-0 text-success" />
                    <span>Draft saved with {pluralize(ideaEmails(idea.definition).length, 'email')}</span>
                </li>
                {idea.reached_since_used ? (
                    <li className="flex items-start gap-2" data-attr="workflow-idea-reached-since">
                        <IconLetter className="mt-0.5 shrink-0 text-secondary" />
                        <span>
                            <strong>{humanFriendlyNumber(idea.reached_since_used)}</strong>{' '}
                            {idea.reached_since_used === 1 ? 'person' : (evidence.audience ?? 'people')} would have got
                            the first email since you saved this draft. They still need to{' '}
                            {evidence.goal ?? 'reach the goal'}.
                        </span>
                    </li>
                ) : null}
                <IdeaSenderStep sender={emailSender} />
                <IdeaLinkStep siteUrl={evidence.site_url} />
                {evidence.review_note && (
                    <li className="flex items-start gap-2">
                        <IconWarning className="mt-0.5 shrink-0 text-warning" />
                        <span>{evidence.review_note}</span>
                    </li>
                )}
                <li className="flex items-start gap-2">
                    <IconClock className="mt-0.5 shrink-0 text-secondary" />
                    <span>Turn it on. Nothing sends until you do.</span>
                </li>
            </ol>
            <div className="mt-auto flex flex-wrap gap-2">
                <IdeaSenderActions sender={emailSender} />
                <LemonButton
                    type={needsSender ? 'secondary' : 'primary'}
                    size="small"
                    to={urls.workflow(hogFlowId, 'workflow')}
                    // pinned: data-attr - autocapture dashboards read it
                    data-attr="workflow-idea-continue"
                >
                    Continue setup
                </LemonButton>
            </div>
        </LemonCard>
    )
}
