import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { urls } from 'scenes/urls'

import { splitRepoFullName } from '../lib/repoPaths'

export type VisualReviewTabKey = 'runs' | 'snapshots' | 'flakiness'

// Top-level tab strip for a repo workspace. All tabs are repo-scoped and
// share the same owner/name segments, so this component is purely
// presentational — the parent scene already knows which repo it's in.
// Settings stays out of this strip: it's a gear button in the scene's header
// actions instead, matching how other products surface team-wide settings.
export function VisualReviewTabs({
    activeKey,
    repoFullName,
}: {
    activeKey: VisualReviewTabKey
    repoFullName: string
}): JSX.Element {
    return (
        <LemonTabs
            activeKey={activeKey}
            sceneInset
            tabs={[
                {
                    key: 'runs' satisfies VisualReviewTabKey,
                    label: 'Runs',
                    link: urls.visualReviewRepoRuns(...splitRepoFullName(repoFullName)),
                },
                {
                    key: 'snapshots' satisfies VisualReviewTabKey,
                    label: 'Snapshots',
                    link: urls.visualReviewSnapshotOverview(...splitRepoFullName(repoFullName)),
                },
                {
                    key: 'flakiness' satisfies VisualReviewTabKey,
                    label: 'Flakiness',
                    link: urls.visualReviewFlakiness(...splitRepoFullName(repoFullName)),
                },
            ]}
        />
    )
}
