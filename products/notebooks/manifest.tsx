import { IconNotebook } from '@posthog/icons'
import { PRODUCT_VISUAL_ORDER } from 'lib/constants'
import { urls } from 'scenes/urls'

import { ProductManifest } from '../../frontend/src/types'

export const manifest: ProductManifest = {
    name: 'Notebooks',
    urls: {
        notebooks: (): string => '/notebooks',
        notebook: (shortId: string): string => `/notebooks/${shortId}`,
        canvas: (): string => `/canvas`,
    },
    fileSystemTypes: {
        notebook: {
            icon: <IconNotebook />,
            href: (ref: string) => urls.notebook(ref),
            iconColor: ['var(--product-notebooks-light)'],
        },
    },
    treeItemsNew: [
        {
            path: `Notebook`,
            type: 'notebook',
            href: urls.notebook('new'),
        },
    ],
    treeItemsProducts: [
        {
            path: 'Notebooks',
            type: 'notebook',
            href: urls.notebooks(),
            visualOrder: PRODUCT_VISUAL_ORDER.notebooks,
        },
    ],
    fileSystemFilterTypes: {
        notebook: { name: 'Notebooks' },
    },
}
