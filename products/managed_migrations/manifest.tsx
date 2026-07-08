import { urls } from 'scenes/urls'

import { ProductManifest } from '../../frontend/src/types'

export const manifest: ProductManifest = {
    name: 'Managed migrations',
    scenes: {
        ManagedMigration: {
            import: () => import('./frontend/ManagedMigration'),
            name: 'Managed migrations',
            description: 'Managed migrations provide an automated way to migrate your historical data into PostHog.',
            projectBased: true,
        },
        ManagedMigrationNew: {
            import: () => import('./frontend/ManagedMigration'),
            name: 'Managed migrations',
            projectBased: true,
        },
    },
    routes: {
        '/managed_migrations': ['ManagedMigration', 'managedMigration'],
        '/managed_migrations/new': ['ManagedMigration', 'managedMigration'],
    },
    urls: {
        managedMigration: (): string => '/managed_migrations',
        managedMigrationNew: (): string => '/managed_migrations/new',
    },
    treeItemsMetadata: [
        {
            path: 'Managed migrations',
            category: 'Pipeline',
            iconType: 'data_pipeline_metadata',
            href: urls.managedMigration(),
            sceneKey: 'ManagedMigration',
            sceneKeys: ['ManagedMigration', 'ManagedMigrationNew'],
        },
    ],
}
