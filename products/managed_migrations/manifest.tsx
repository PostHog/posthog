import { ProductManifest } from '../../frontend/src/types'

export const manifest: ProductManifest = {
    name: 'Managed migrations',
    scenes: {
        ManagedMigration: {
            import: () => import('./frontend/ManagedMigration'),
            name: 'Managed migrations',
            projectBased: true,
        },
        ManagedMigrationNew: {
            import: () => import('./frontend/ManagedMigration'),
            name: 'Managed migrations',
            projectBased: true,
        },
    },
    routes: {
        // URL: [Scene, SceneKey]
        '/managed_migrations': ['ManagedMigration', 'managedMigration'],
        '/managed_migrations/new': ['ManagedMigration', 'managedMigration'],
    },
    urls: {
        managedMigration: (): string => '/managed_migrations',
        managedMigrationNew: (): string => '/managed_migrations/new',
    },
    // fileSystemTypes: {
    //     'hog_function/broadcast': {
    //         icon: <IconMegaphone />,
    //         href: (ref: string) => urls.messagingBroadcast(ref),
    //     },
    //     'hog_function/campaign': {
    //         icon: <IconMegaphone />,
    //         href: (ref: string) => urls.messagingCampaign(ref),
    //     },
    // },
    // treeItemsNew: [
    //     {
    //         path: `Broadcast`,
    //         type: 'hog_function/broadcast',
    //         href: urls.messagingBroadcastNew(),
    //         flag: FEATURE_FLAGS.MESSAGING,
    //     },
    //     {
    //         path: `Campaign`,
    //         type: 'hog_function/campaign',
    //         href: urls.messagingCampaignNew(),
    //         flag: FEATURE_FLAGS.MESSAGING_AUTOMATION,
    //     },
    // ],
    // treeItemsProducts: [
    //     {
    //         path: 'Broadcasts',
    //         href: urls.messagingBroadcasts(),
    //         type: 'hog_function/broadcast',
    //     },
    //     {
    //         path: 'Campaigns',
    //         href: urls.messagingCampaigns(),
    //         type: 'hog_function/campaign',
    //     },
    // ],
    // fileSystemFilterTypes: {
    //     broadcast: { name: 'Broadcasts', flag: FEATURE_FLAGS.MESSAGING },
    //     campaign: { name: 'Campaigns', flag: FEATURE_FLAGS.MESSAGING_AUTOMATION },
    // },
}
