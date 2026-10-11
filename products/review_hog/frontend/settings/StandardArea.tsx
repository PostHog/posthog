import { InstallationClaims } from 'products/review_hog/frontend/repositories/InstallationClaims'
import { RepositoriesPanes } from 'products/review_hog/frontend/repositories/RepositoriesPanes'

import { AreaHeader } from './AreaHeader'

// The Standard wording is still under test, so it lives in one place to swap.
const STANDARD_DEFINITION =
    'Standard runs automatically on every push. The same set of reviewers reads the whole change and comments with issues for you to fix. It never pushes to your branch and has no settings of its own.'

export function StandardArea(): JSX.Element {
    return (
        <section className="flex flex-col gap-3">
            <AreaHeader title="Standard" subtitle="who gets automatic reviews">
                <p className="m-0 text-sm">
                    {STANDARD_DEFINITION} The rules below decide who gets it. No automatic review runs on a pull request
                    after it had a Deep review.
                </p>
            </AreaHeader>
            <InstallationClaims />
            <RepositoriesPanes />
        </section>
    )
}
