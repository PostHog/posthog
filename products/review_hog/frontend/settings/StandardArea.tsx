import { SceneSection } from '~/layout/scenes/components/SceneSection'

import { InstallationClaims } from 'products/review_hog/frontend/repositories/InstallationClaims'
import { RepositoriesTable } from 'products/review_hog/frontend/repositories/RepositoriesTable'

import { StandardSettingsSection } from './StandardSettingsSection'

export function StandardArea(): JSX.Element {
    return (
        <SceneSection
            title="Standard reviews"
            description="Standard reviews run on every push and only comment on your pull request."
            titleHelper="Standard reviews never push to your branch. A pull request that already had a Deep review gets no more automatic reviews."
        >
            <InstallationClaims />
            <StandardSettingsSection />
            <RepositoriesTable />
        </SceneSection>
    )
}
