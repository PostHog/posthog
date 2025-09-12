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
            name: 'Notebook',
            iconType: 'notebook',
            href: (ref: string) => urls.notebook(ref),
            filterKey: 'notebook',
        },
    },
    treeItemsNew: [
        {
            path: `Notebook`,
            type: 'notebook',
            href: urls.notebook('new'),
            iconType: 'notebook',
        },
    ],
}
