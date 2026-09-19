import { Link } from '@posthog/lemon-ui'

import { NotFound } from 'lib/components/NotFound'

export function RunNotFound(): JSX.Element {
    return (
        <NotFound
            object="run"
            caption={
                <>
                    This run may belong to a project you don't have access to, or it may have been deleted. A run link
                    switches you to its project when you have access, so ask the person who sent you the link to check
                    the project and give you access. You can also{' '}
                    <Link to="/visual_review" data-attr="visual-review-run-not-found-browse-runs">
                        browse the runs in this project
                    </Link>
                    .
                </>
            }
        />
    )
}
