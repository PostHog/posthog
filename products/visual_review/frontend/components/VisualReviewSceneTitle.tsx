import { useValues } from 'kea'

import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { visualReviewRepoLogic } from '../scenes/visualReviewRepoLogic'
import { RepoSwitcher } from './RepoSwitcher'
import type { VisualReviewTabKey } from './VisualReviewTabs'

export interface VisualReviewSceneTitleProps {
    /** The repository named in the URL. The title shows the stored spelling once the repository loads. */
    repoFullName: string
    /** The tab that owns this page. Switching repository lands on this tab in the other repository. */
    activeTab: VisualReviewTabKey
    actions?: JSX.Element
}

/** The title every repository page shares: the repository it shows, with the switch button beside it.
 *  The breadcrumbs above carry the product name, and a page about one run or snapshot names it in its own trail. */
export function VisualReviewSceneTitle({ repoFullName, activeTab, actions }: VisualReviewSceneTitleProps): JSX.Element {
    const { repo } = useValues(visualReviewRepoLogic({ repoFullName }))
    return (
        <SceneTitleSection
            name={repo?.repo_full_name ?? repoFullName}
            nameSuffix={<RepoSwitcher repoFullName={repoFullName} activeTab={activeTab} />}
            resourceType={{ type: 'visual_review' }}
            actions={actions}
        />
    )
}
