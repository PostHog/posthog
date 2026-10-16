import { useValues } from 'kea'

import { IconChevronDown } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { LemonMenu } from 'lib/lemon-ui/LemonMenu/LemonMenu'
import { urls } from 'scenes/urls'

import type { RepoApi } from '../generated/api.schemas'
import { splitRepoFullName } from '../lib/repoPaths'
import { visualReviewRepoLogic } from '../scenes/visualReviewRepoLogic'
import type { VisualReviewTabKey } from './VisualReviewTabs'

interface RepoSwitcherProps {
    repoFullName: string
    // Where to land on the other repo. It preserves the user's current tab, so
    // switching from Snapshots on repo A goes to Snapshots on repo B. A detail page passes the tab that owns it.
    activeTab: VisualReviewTabKey
}

const TAB_TO_PATH: Record<VisualReviewTabKey, (repoFullName: string) => string> = {
    runs: (repoFullName) => urls.visualReviewRepoRuns(...splitRepoFullName(repoFullName)),
    snapshots: (repoFullName) => urls.visualReviewSnapshotOverview(...splitRepoFullName(repoFullName)),
    flakiness: (repoFullName) => urls.visualReviewFlakiness(...splitRepoFullName(repoFullName)),
}

export function RepoSwitcher({ repoFullName, activeTab }: RepoSwitcherProps): JSX.Element | null {
    const { otherRepos } = useValues(visualReviewRepoLogic({ repoFullName }))

    if (otherRepos.length === 0) {
        return null
    }

    const items = otherRepos.map((r: RepoApi) => ({
        label: r.repo_full_name,
        to: TAB_TO_PATH[activeTab](r.repo_full_name),
    }))

    return (
        <LemonMenu items={items}>
            <LemonButton
                type="secondary"
                size="small"
                sideIcon={<IconChevronDown />}
                data-attr="visual-review-repo-switcher"
            >
                Switch repository
            </LemonButton>
        </LemonMenu>
    )
}
