import { useActions } from 'kea'

import { Link } from '@posthog/lemon-ui'

import { newAccountMenuLogic } from 'lib/components/Account/newAccountMenuLogic'
import { NotFound } from 'lib/components/NotFound'

export function RunNotFound(): JSX.Element {
    const { openProjectSwitcher } = useActions(newAccountMenuLogic)

    return (
        <NotFound
            object="run"
            caption={
                <>
                    This run may belong to a different project. A visual review link opens in the project you have
                    active, so{' '}
                    <Link onClick={openProjectSwitcher} data-attr="visual-review-run-not-found-switch-project">
                        switch project
                    </Link>{' '}
                    and open the link again. You can also{' '}
                    <Link to="/visual_review" data-attr="visual-review-run-not-found-browse-runs">
                        browse the runs in this project
                    </Link>
                    .
                </>
            }
        />
    )
}
