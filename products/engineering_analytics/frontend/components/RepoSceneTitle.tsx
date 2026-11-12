import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { RepoSwitcher } from './RepoSwitcher'

export interface RepoSceneTitleProps {
    repo: string | null
    description?: string
    actions?: JSX.Element
}

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
