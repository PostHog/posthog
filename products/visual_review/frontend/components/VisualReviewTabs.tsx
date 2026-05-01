import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { urls } from 'scenes/urls'

export type VisualReviewTabKey = 'runs' | 'snapshots'

// Top-level tab strip for a repo workspace. Both tabs are repo-scoped and
// share the same `:repoId` segment, so this component is purely
// presentational — the parent scene already knows which repo it's in.
// Settings stays out of this strip: it's a gear button in the scene's header
// actions instead, matching how other products surface team-wide settings.
export function VisualReviewTabs({
    activeKey,
    repoId,
}: {
    activeKey: VisualReviewTabKey
    repoId: string
}): JSX.Element {
    return (
        <LemonTabs
            activeKey={activeKey}
            sceneInset
            tabs={[
                {
                    key: 'runs' satisfies VisualReviewTabKey,
                    label: 'Runs',
                    link: urls.visualReviewRepoRuns(repoId),
                },
                {
                    key: 'snapshots' satisfies VisualReviewTabKey,
                    label: 'Snapshots',
                    link: urls.visualReviewSnapshotOverview(repoId),
                },
            ]}
        />
    )
}
