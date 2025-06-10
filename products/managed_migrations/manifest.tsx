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
}
