import { IconNotebook } from '@posthog/icons'

import { urls } from 'scenes/urls'

import { FileSystemIconColor, ProductManifest } from '../../frontend/src/types'

export const manifest: ProductManifest = {
    name: 'Notebooks',
    urls: {
        notebooks: (): string => '/notebooks',
        notebook: (shortId: string): string => `/notebooks/${shortId}`,
        canvas: (): string => `/canvas`,
    },
    fileSystemTypes: {
        notebook: {
            name: 'Notebook',
            icon: <IconNotebook />,
            href: (ref: string) => urls.notebook(ref),
            filterKey: 'notebook',
            iconColor: ['var(--color-product-notebooks-light)'] as FileSystemIconColor,
        },
    },
    treeItemsNew: [
        {
            path: `Notebook`,
            type: 'notebook',
            href: urls.notebook('new'),
            icon: <IconNotebook />,
            iconColor: ['var(--color-product-notebooks-light)'] as FileSystemIconColor,
        },
    ],
}
