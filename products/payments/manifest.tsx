import { ProductManifest } from '../../frontend/src/types'

export const manifest: ProductManifest = {
    name: 'Payments',
    scenes: {
        PaymentsOverview: {
            import: () => import('./frontend/scenes/overview/PaymentsOverviewScene'),
            name: 'Payments overview',
            projectBased: true,
        },
        PaymentsProducts: {
            import: () => import('./frontend/scenes/products/PaymentsProductsScene'),
            name: 'Payments products',
            projectBased: true,
        },
        PaymentsTransactions: {
            import: () => import('./frontend/scenes/transactions/PaymentsTransactionsScene'),
            name: 'Payments transactions',
            projectBased: true,
        },
        PaymentsSettings: {
            import: () => import('./frontend/scenes/settings/PaymentsSettingsScene'),
            name: 'Payments settings',
            projectBased: true,
        },
    },
    routes: {
        // URL: [Scene, SceneKey]
        '/payments': ['PaymentsOverview', 'paymentsOverview'],
        '/payments/products': ['PaymentsProducts', 'paymentsProducts'],
        '/payments/transactions': ['PaymentsTransactions', 'paymentsTransactions'],
        '/payments/settings': ['PaymentsSettings', 'paymentsSettings'],
    },
    redirects: {},
    urls: {
        paymentsOverview: (): string => `/payments`,
        paymentsProducts: (): string => `/payments/products`,
        paymentsTransactions: (): string => `/payments/transactions`,
        paymentsSettings: (): string => `/payments/settings`,
    },
    fileSystemTypes: {},
    treeItemsNew: [],
}
