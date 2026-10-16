import { IconGitBranch } from '@posthog/icons'
import { ChatMarkerValue } from '@posthog/quill-primitives'

import { ThreadMarker } from './ThreadMarker'

export interface QuillRunContextRowProps {
    branch: string
    baseBranch?: string
    repo?: string
}

export function QuillRunContextRow({ branch, baseBranch, repo }: QuillRunContextRowProps): JSX.Element {
    return (
        <ThreadMarker icon={<IconGitBranch />}>
            <span data-attr="max-sandbox-run-context">Working on</span>
            {repo && <ChatMarkerValue>{repo}</ChatMarkerValue>}
            <ChatMarkerValue className="font-mono">{baseBranch ? `${branch} → ${baseBranch}` : branch}</ChatMarkerValue>
        </ThreadMarker>
    )
}
