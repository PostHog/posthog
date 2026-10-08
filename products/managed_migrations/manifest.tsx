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
        // nosemgrep: frontend-route-hyphen -- shipped app URL, existing links point here
        '/managed_migrations': ['ManagedMigration', 'managedMigration'],
        // nosemgrep: frontend-route-hyphen -- shipped app URL, existing links point here
        '/managed_migrations/new': ['ManagedMigration', 'managedMigration'],
    },
    urls: {
        managedMigration: (): string => '/managed_migrations',
        managedMigrationNew: (): string => '/managed_migrations/new',
    },
    treeItemsMetadata: [
        {
            path: 'Managed migrations',
            category: 'CDP',
            iconType: 'managed_migration',
            iconColor: [
                'var(--color-product-managed-migrations-light)',
                'var(--color-product-managed-migrations-dark)',
            ],
            href: urls.managedMigration(),
            sceneKey: 'ManagedMigration',
            sceneKeys: ['ManagedMigration', 'ManagedMigrationNew'],
        },
    ],
}
