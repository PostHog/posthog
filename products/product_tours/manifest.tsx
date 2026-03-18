import { FEATURE_FLAGS } from 'lib/constants'
import { urls } from 'scenes/urls'

import { ProductKey } from '~/queries/schema/schema-general'
import { FileSystemIconColor, ProductManifest } from '~/types'

export const manifest: ProductManifest = {
    name: 'Product tours',
    urls: {
        productTours: (): string => '/product_tours',
        productTour: (id: string): string => `/product_tours/${id}`,
    },
    fileSystemTypes: {
        product_tour: {
            name: 'Product tour',
            iconType: 'product_tour',
            href: (ref: string) => urls.productTour(ref),
            iconColor: ['var(--color-product-surveys-light)'],
            filterKey: 'product_tour',
        },
    },
    treeItemsNew: [
        {
            path: `Product tour`,
            type: 'product_tour',
            href: urls.productTour('new'),
            iconType: 'product_tour',
            iconColor: ['var(--color-product-surveys-light)'] as FileSystemIconColor,
        },
    ],
    treeItemsProducts: [
        {
            path: 'Product tours',
            intents: [ProductKey.PRODUCT_TOURS],
            category: 'Behavior',
            type: 'product_tour',
            href: urls.productTours(),
            iconType: 'product_tour',
            iconColor: ['var(--color-product-surveys-light)'] as FileSystemIconColor,
            sceneKey: 'ProductTours',
            sceneKeys: ['ProductTour', 'ProductTours'],
            flag: FEATURE_FLAGS.PRODUCT_TOURS,
        },
    ],
}
