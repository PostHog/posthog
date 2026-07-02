import { IconPullRequest, IconXCircle } from '@posthog/icons'
import { LemonTag, LemonTagType } from '@posthog/lemon-ui'

import { PRState } from '../scenes/engineeringAnalyticsLogic'

// GitHub's state palette: open green, draft grey, merged purple, closed red. Draft is a lens over open
// PRs, so it gets its own entry though it isn't a PRState.
const STATE_CONFIG: Record<PRState | 'draft', { label: string; type: LemonTagType; icon: JSX.Element }> = {
    open: { label: 'Open', type: 'success', icon: <IconPullRequest /> },
    draft: { label: 'Draft', type: 'muted', icon: <IconPullRequest /> },
    merged: { label: 'Merged', type: 'completion', icon: <IconPullRequest /> },
    closed: { label: 'Closed', type: 'danger', icon: <IconXCircle /> },
}

export function PullRequestStateTag({ state, isDraft }: { state: PRState; isDraft: boolean }): JSX.Element {
    // Fall back to a muted tag of the raw value if the API ever sends a state outside the enum.
    const { label, type, icon } = STATE_CONFIG[state === 'open' && isDraft ? 'draft' : state] ?? {
        label: state,
        type: 'muted' as LemonTagType,
        icon: <IconPullRequest />,
    }
    return (
        <LemonTag type={type} icon={icon}>
            {label}
        </LemonTag>
    )
}
