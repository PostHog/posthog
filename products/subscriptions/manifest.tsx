import { ProductManifest } from '../../frontend/src/types'

export const manifest: ProductManifest = {
    name: 'Subscriptions',
    scenes: {
        Subscriptions: {
            import: () => import('./frontend/scenes/SubscriptionsScene'),
            projectBased: true,
            name: 'Subscriptions',
            iconType: 'inbox',
            description: 'View and manage scheduled insight and dashboard subscriptions for this project.',
        },
        Subscription: {
            import: () => import('./frontend/scenes/SubscriptionScene'),
            projectBased: true,
            name: 'Subscription',
            iconType: 'inbox',
            description: 'View subscription details and delivery history for this project.',
        },
    },
    routes: {
        '/subscriptions': ['Subscriptions', 'subscriptions'],
        // Static + edit routes MUST come before `/subscriptions/:subscriptionId`,
        // otherwise the wildcard captures "new" / "<id>/edit" and mounts the detail
        // scene → 404 "Subscription not found" with a removeChild reconciliation
        // error from the racing mounts.
        '/subscriptions/new': ['Subscriptions', 'subscriptionNew'],
        '/subscriptions/:subscriptionId/edit': ['Subscriptions', 'subscriptionEdit'],
        '/subscriptions/:subscriptionId': ['Subscription', 'subscription'],
    },
    urls: {
        subscriptions: (): string => '/subscriptions',
        subscription: (id: string | number): string => `/subscriptions/${id}`,
        subscriptionNew: (): string => '/subscriptions/new',
        subscriptionEdit: (id: string | number): string => `/subscriptions/${id}/edit`,
    },
    fileSystemTypes: {},
    treeItemsNew: [],
    treeItemsProducts: [],
}
