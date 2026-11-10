import { IconExternal, IconPullRequest } from '@posthog/icons'
import { Button, ChatMarkerValue } from '@posthog/quill-primitives'

import { LinkPrimitive } from 'lib/lemon-ui/Link'

import { ThreadMarker } from './ThreadMarker'

export function QuillPullRequestRow({ prUrl, branch }: { prUrl: string; branch?: string }): JSX.Element {
    return (
        <div className="flex items-center gap-2" data-attr="max-sandbox-pr-card">
            {/* A narrow thread puts the branch under the label, so more of its name shows beside the button. */}
            <ThreadMarker icon={<IconPullRequest />} className="min-w-0 flex-1 opacity-100 text-foreground">
                <span className="flex min-w-0 items-baseline @max-lg/thread:flex-col @max-lg/thread:items-start">
                    <span className="shrink-0 font-medium">Pull request opened</span>
                    {branch && (
                        <ChatMarkerValue className="max-w-full min-w-0 truncate font-mono @max-lg/thread:ms-0 @max-lg/thread:text-xs @max-lg/thread:text-(--muted-foreground) @max-lg/thread:before:content-none @max-lg/thread:after:content-none">
                            {branch}
                        </ChatMarkerValue>
                    )}
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
