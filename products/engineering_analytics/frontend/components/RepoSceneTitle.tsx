import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { RepoSwitcher } from './RepoSwitcher'

export interface RepoSceneTitleProps {
    repo: string | null
    description?: string
    actions?: JSX.Element
}

/** The title every page of the product shares: the repository it shows, with the switch button beside it.
 *  The breadcrumbs above carry the product name, and a page about one entity names it in its own header. */
export function RepoSceneTitle({ repo, description, actions }: RepoSceneTitleProps): JSX.Element {
    return (
        <SceneTitleSection
            name={repo ?? 'Engineering analytics'}
            nameSuffix={<RepoSwitcher />}
            description={description}
            resourceType={{ type: 'health' }}
            actions={actions}
        />
    )
}
