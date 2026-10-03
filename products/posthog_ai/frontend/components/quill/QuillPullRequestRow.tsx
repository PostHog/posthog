import { IconExternal, IconPullRequest } from '@posthog/icons'
import { Button, ChatMarkerValue } from '@posthog/quill-primitives'

import { LinkPrimitive } from 'lib/lemon-ui/Link'

import { ThreadMarker } from './ThreadMarker'

export function QuillPullRequestRow({ prUrl, branch }: { prUrl: string; branch?: string }): JSX.Element {
    return (
        <div className="flex items-center gap-2" data-attr="max-sandbox-pr-card">
            {/* The label keeps one line and a long branch truncates, so the button stays beside them. */}
            <ThreadMarker icon={<IconPullRequest />} className="min-w-0 flex-1 opacity-100 text-foreground">
                <span className="flex min-w-0 items-baseline">
                    <span className="shrink-0 font-medium">Pull request opened</span>
                    {branch && <ChatMarkerValue className="min-w-0 truncate font-mono">{branch}</ChatMarkerValue>}
                </span>
            </ThreadMarker>
            <Button
                variant="outline"
                size="xs"
                className="shrink-0"
                render={<LinkPrimitive to={prUrl} target="_blank" />}
            >
                Open on GitHub
                <IconExternal />
            </Button>
        </div>
    )
}
