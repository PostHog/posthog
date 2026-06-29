import { IconPullRequest, IconXCircle } from '@posthog/icons'
import { LemonTag, LemonTagType } from '@posthog/lemon-ui'

import { PRState } from '../scenes/engineeringAnalyticsLogic'

// GitHub's own state palette so the badge reads at a glance: open green, draft grey, merged purple,
// closed red. Draft is a lens over open PRs, so it gets its own entry here even though it isn't a PRState.
const STATE_CONFIG: Record<PRState | 'draft', { label: string; type: LemonTagType; icon: JSX.Element }> = {
    open: { label: 'Open', type: 'success', icon: <IconPullRequest /> },
    draft: { label: 'Draft', type: 'muted', icon: <IconPullRequest /> },
    merged: { label: 'Merged', type: 'completion', icon: <IconPullRequest /> },
    closed: { label: 'Closed', type: 'danger', icon: <IconXCircle /> },
}

export function PullRequestStateTag({ state, isDraft }: { state: PRState; isDraft: boolean }): JSX.Element {
    const { label, type, icon } = STATE_CONFIG[state === 'open' && isDraft ? 'draft' : state]
    return (
        <LemonTag type={type} icon={icon}>
            {label}
        </LemonTag>
    )
}
