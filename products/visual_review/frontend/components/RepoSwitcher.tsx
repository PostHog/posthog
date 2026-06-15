import { useValues } from 'kea'

import { IconChevronDown } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { LemonMenu } from 'lib/lemon-ui/LemonMenu/LemonMenu'

import type { RepoApi } from '../generated/api.schemas'
import { visualReviewRepoLogic } from '../scenes/visualReviewRepoLogic'
import type { VisualReviewTabKey } from './VisualReviewTabs'

interface RepoSwitcherProps {
    repoId: string
    // Where to land on the other repo — preserves the user's current tab so
    // switching from Snapshots on repo A goes to Snapshots on repo B.
    activeTab: VisualReviewTabKey
}

const TAB_TO_PATH: Record<VisualReviewTabKey, (repoId: string) => string> = {
    runs: (repoId) => `/visual_review/repos/${repoId}/runs`,
    snapshots: (repoId) => `/visual_review/repos/${repoId}/snapshots`,
}

export function RepoSwitcher({ repoId, activeTab }: RepoSwitcherProps): JSX.Element | null {
    const { repo, otherRepos } = useValues(visualReviewRepoLogic({ repoId }))

    if (otherRepos.length === 0) {
        return null
    }

    const items = otherRepos.map((r: RepoApi) => ({
        label: r.repo_full_name,
        to: TAB_TO_PATH[activeTab](r.id),
    }))

    return (
        <LemonMenu items={items}>
            <LemonButton type="secondary" size="small" sideIcon={<IconChevronDown />}>
                {repo?.repo_full_name ?? 'Switch repo'}
            </LemonButton>
        </LemonMenu>
    )
}
