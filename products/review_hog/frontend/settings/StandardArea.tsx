import { SceneSection } from '~/layout/scenes/components/SceneSection'

import { InstallationClaims } from 'products/review_hog/frontend/repositories/InstallationClaims'
import { RepositoriesPanes } from 'products/review_hog/frontend/repositories/RepositoriesPanes'

export function StandardArea(): JSX.Element {
    return (
        <SceneSection
            title="Standard reviews"
            description="Automatic comments on each push. Never changes your branch. Stops after a Deep review."
        >
            <InstallationClaims />
            <RepositoriesPanes />
        </SceneSection>
    )
}
