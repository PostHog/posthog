import * as directorPng from '@posthog/brand/hoggies/png/director'
import { IconSpotlight } from '@posthog/icons'

import { pngHoggie } from 'lib/brand/hoggies'
import type { SceneProductEmptyState } from 'lib/components/ProductEmptyState/types'
import { FEATURE_FLAGS } from 'lib/constants'

import { ProductKey } from '~/queries/schema/schema-general'

import { ProductTourPreview } from './ProductTourPreview'
import { productToursSetupLogic } from './productToursSetupLogic'

const HedgehogDirector = pngHoggie(directorPng)

export const productToursEmptyState: SceneProductEmptyState = {
    statusLogic: productToursSetupLogic,
    // The whole product is behind this flag; the scene's own 404 gate handles the flag-off case.
    featureFlag: FEATURE_FLAGS.PRODUCT_TOURS,
    config: {
        productKey: ProductKey.PRODUCT_TOURS,
        productName: 'Product tours',
        icon: <IconSpotlight />,
        accentColor: 'var(--color-product-product-tours-light)',
        accentColorDark: 'var(--color-product-product-tours-dark)',
        hedgehog: HedgehogDirector,
        text: {
            'needs-setup': {
                headline: 'Show users what to do next, right in your app',
                lead: 'Build multi-step tours that point at real elements in your product, plus announcements and banners for one-off messages. Steps can highlight an element, open a modal, or pin a banner, and feature flags control exactly who sees each tour. No redeploy needed to launch, change, or stop one.',
            },
        },
        primaryAction: {
            label: 'Create your first tour',
            onClick: () => productToursSetupLogic.findMounted()?.actions.createTour('My first tour'),
            dataAttr: 'new-product-tour',
        },
        skippable: false,
        docsUrl: 'https://posthog.com/docs/product-tours',
        previewLabel: 'Your tours, once live',
        Preview: ProductTourPreview,
    },
}
