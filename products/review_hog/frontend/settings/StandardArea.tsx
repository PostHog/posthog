import { SceneSection } from '~/layout/scenes/components/SceneSection'

import { InstallationClaims } from 'products/review_hog/frontend/repositories/InstallationClaims'
import { RepositoriesPanes } from 'products/review_hog/frontend/repositories/RepositoriesPanes'

export function StandardArea(): JSX.Element {
    return (
        <SceneSection
            title="Standard reviews"
            description="One automatic review per pull request, unless it already has a Deep review. Never changes your branch."
        >
            <InstallationClaims />
            <RepositoriesPanes />
        </SceneSection>
    )
}
