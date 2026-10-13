import { SceneSection } from '~/layout/scenes/components/SceneSection'

import { InstallationClaims } from 'products/review_hog/frontend/repositories/InstallationClaims'
import { RepositoriesPanes } from 'products/review_hog/frontend/repositories/RepositoriesPanes'

// The Standard wording is still under test, so it lives in one place to swap.
const STANDARD_DEFINITION =
    'Standard runs on every push and comments on your pull request. It never pushes to your branch.'

export function StandardArea(): JSX.Element {
    return (
        <SceneSection
            title="Standard · who gets automatic reviews"
            description={`${STANDARD_DEFINITION} The rules below decide who gets it. A pull request that had a Deep review gets no more Standard reviews.`}
        >
            <InstallationClaims />
            <RepositoriesPanes />
        </SceneSection>
    )
}
