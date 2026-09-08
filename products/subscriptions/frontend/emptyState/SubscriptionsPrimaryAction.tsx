import { useActions } from 'kea'
import { router } from 'kea-router'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { urls } from 'scenes/urls'

import { SubscriptionsSceneModal } from '../scenes/components/SubscriptionsSceneModal'

/**
 * Create button for the subscriptions empty state. The creation modal belongs to the
 * scene the gate replaces, so the empty state renders it too - otherwise the button
 * would change the URL and open nothing.
 */
export function SubscriptionsPrimaryAction(): JSX.Element {
    const { push } = useActions(router)

    return (
        <>
            <LemonButton
                type="primary"
                onClick={() => push(urls.subscriptionNew())}
                data-attr="new-subscription-button"
            >
                Create your first subscription
            </LemonButton>
            <SubscriptionsSceneModal />
        </>
    )
}
