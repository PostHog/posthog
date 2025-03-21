import { IconHandMoney } from '@posthog/icons'
import { urls } from 'scenes/urls'

import { ProductManifest } from '../../frontend/src/types'

export const manifest: ProductManifest = {
    name: 'Payments',
    urls: {
        overview: (): string => `/payments`,
        products: (): string => `/payments/products`,
        transactions: (): string => `/payments/transactions`,
        settings: (): string => `/payments/settings`,
    },
    fileSystemTypes: {},
    treeItems: [
        {
            path: 'Payments/Overview',
            href: () => urls.paymentsOverview(),
            icon: <IconHandMoney />,
        },
        {
            path: 'Payments/Products',
            href: () => urls.paymentsProducts(),
            icon: <IconHandMoney />,
        },
        {
            path: 'Payments/Transactions',
            href: () => urls.paymentsTransactions(),
            icon: <IconHandMoney />,
        },
        {
            path: 'Payments/Settings',
            href: () => urls.paymentsSettings(),
            icon: <IconHandMoney />,
        },
    ],
}
