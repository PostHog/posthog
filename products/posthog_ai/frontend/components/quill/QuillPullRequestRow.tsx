import { IconExternal, IconPullRequest } from '@posthog/icons'
import { Button, ChatMarkerValue } from '@posthog/quill-primitives'

import { LinkPrimitive } from 'lib/lemon-ui/Link'

import { ThreadMarker } from './ThreadMarker'

export function QuillPullRequestRow({ prUrl, branch }: { prUrl: string; branch?: string }): JSX.Element {
    return (
        <div className="flex items-center gap-2" data-attr="max-sandbox-pr-card">
            <ThreadMarker icon={<IconPullRequest />} className="opacity-100">
                <span className="font-medium">Pull request opened</span>
                {branch && <ChatMarkerValue className="font-mono">{branch}</ChatMarkerValue>}
            </ThreadMarker>
            <Button variant="outline" size="xs" render={<LinkPrimitive to={prUrl} target="_blank" />}>
                Open on GitHub
                <IconExternal />
            </Button>
        </div>
    )
}
