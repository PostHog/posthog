import { FEATURE_FLAGS } from 'lib/constants'
import { urls } from 'scenes/urls'

import { ProductItemCategory, ProductKey } from '~/queries/schema/schema-general'
import { ActivityScope, FileSystemIconColor, ProductManifest } from '~/types'

export const manifest: ProductManifest = {
    name: 'Product tours',
    activityDescribers: {
        [ActivityScope.PRODUCT_TOUR]: () =>
            import('scenes/product-tours/activityDescriptions').then((module) => module.productTourActivityDescriber),
    },
    urls: {
        productTours: (): string => '/product_tours',
        productTour: (id: string): string => `/product_tours/${id}`,
    },
    fileSystemTypes: {
        product_tour: {
            name: 'Product tour',
            iconType: 'product_tour',
            href: (ref: string) => urls.productTour(ref),
            listHref: () => urls.productTours(),
            iconColor: ['var(--color-product-product-tours-light)', 'var(--color-product-product-tours-dark)'],
            filterKey: 'product_tour',
            // Gate the type on the same flag as the ProductTours scene, which renders a 404 without it.
            // Without this, Library object-type rows and tree type filters offer "Product tours" to
            // everyone and link into that 404.
            flag: FEATURE_FLAGS.PRODUCT_TOURS,
        },
    },
    treeItemsNew: [
        {
            path: `Product tour`,
            type: 'product_tour',
            href: urls.productTour('new'),
            iconType: 'product_tour',
            iconColor: [
                'var(--color-product-product-tours-light)',
                'var(--color-product-product-tours-dark)',
            ] as FileSystemIconColor,
            flag: FEATURE_FLAGS.PRODUCT_TOURS,
        },
    ],
    treeItemsProducts: [
        {
            path: 'Product tours',
            intents: [ProductKey.PRODUCT_TOURS],
            category: ProductItemCategory.PRODUCT_ENGINEERING,
            type: 'product_tour',
            href: urls.productTours(),
            searchKeywords: ['walkthrough', 'onboarding flows', 'tooltips'],
            iconType: 'product_tour',
            iconColor: [
                'var(--color-product-product-tours-light)',
                'var(--color-product-product-tours-dark)',
            ] as FileSystemIconColor,
            sceneKey: 'ProductTours',
            sceneKeys: ['ProductTour', 'ProductTours'],
            flag: FEATURE_FLAGS.PRODUCT_TOURS,
        },
    ],
}
