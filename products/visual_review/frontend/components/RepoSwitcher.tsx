import { useValues } from 'kea'

import { IconChevronDown } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { LemonMenu } from 'lib/lemon-ui/LemonMenu/LemonMenu'
import { urls } from 'scenes/urls'

import type { RepoApi } from '../generated/api.schemas'
import { visualReviewRepoLogic } from '../scenes/visualReviewRepoLogic'
import type { VisualReviewTabKey } from './VisualReviewTabs'

interface RepoSwitcherProps {
    repoFullName: string
    // Where to land on the other repo — preserves the user's current tab so
    // switching from Snapshots on repo A goes to Snapshots on repo B.
    activeTab: VisualReviewTabKey
}

const TAB_TO_PATH: Record<VisualReviewTabKey, (repoFullName: string) => string> = {
    runs: (repoFullName) => urls.visualReviewRepoRuns(repoFullName),
    snapshots: (repoFullName) => urls.visualReviewSnapshotOverview(repoFullName),
    flakiness: (repoFullName) => urls.visualReviewFlakiness(repoFullName),
}

export function RepoSwitcher({ repoFullName, activeTab }: RepoSwitcherProps): JSX.Element | null {
    const { repo, otherRepos } = useValues(visualReviewRepoLogic({ repoFullName }))

    if (otherRepos.length === 0) {
        return null
    }

    const items = otherRepos.map((r: RepoApi) => ({
        label: r.repo_full_name,
        to: TAB_TO_PATH[activeTab](r.repo_full_name),
    }))

    return (
        <LemonMenu items={items}>
            <LemonButton type="secondary" size="small" sideIcon={<IconChevronDown />}>
                {repo?.repo_full_name ?? repoFullName}
            </LemonButton>
        </LemonMenu>
    )
}
