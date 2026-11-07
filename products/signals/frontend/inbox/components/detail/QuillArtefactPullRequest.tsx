import { IconExternal, IconPullRequest } from '@posthog/icons'
import { Badge, Text } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'

import type { SignalReportPullRequestApi } from 'products/signals/frontend/generated/api.schemas'

import { type ArtefactPullRequestOutcome, artefactPullRequestView } from './artefactLogPresentation'
import { quillBadgeVariant } from './quillBadgeVariant'

/** The quill sibling of `ArtefactPullRequest`: a pull request the report produced or replaced. */
export function QuillArtefactPullRequest({
    url,
    implementationTitle,
    state,
    outcome,
}: {
    url: string
    implementationTitle?: string
    state?: SignalReportPullRequestApi['state']
    outcome?: ArtefactPullRequestOutcome
}): JSX.Element {
    const view = artefactPullRequestView({ url, implementationTitle, state, outcome })

    return (
        <div className="flex min-w-0 flex-col gap-1.5" data-attr="inbox-activity-pull-request">
            <div className="flex min-w-0 flex-wrap items-center gap-1.5 text-muted-foreground">
                <IconPullRequest className="size-4 shrink-0" />
                <Text size="xs" variant="muted" render={<span />} className="break-all">
                    {view.repoLabel}
                </Text>
                <Badge variant={quillBadgeVariant(view.statusTagType)}>{view.statusLabel}</Badge>
            </div>
            <LinkPrimitive
                to={url}
                target="_blank"
                className="min-w-0 break-words text-sm font-medium text-primary wrap-anywhere hover:underline"
                data-attr="inbox-activity-pull-request-link"
                title={implementationTitle ? 'Implementation task title' : undefined}
            >
                {view.linkText}
                <IconExternal className="ms-1 inline size-3.5" />
            </LinkPrimitive>
            {view.outcomeLabel ? (
                <Text size="xs" variant="muted" render={<span />}>
                    {view.outcomeLabel}
                </Text>
            ) : null}
        </div>
    )
}
