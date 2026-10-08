import { urls } from 'scenes/urls'

import { ProductManifest } from '../../frontend/src/types'

export const manifest: ProductManifest = {
    name: 'Notebooks',
    scenes: {
        ReusableWidget: {
            name: 'Reusable widget',
            import: () => import('./frontend/ReusableWidget/ReusableWidgetScene'),
            projectBased: true,
            activityScope: 'Notebook',
            iconType: 'notebook',
        },
    },
    routes: {
        '/notebooks/widgets/:widgetId': ['ReusableWidget', 'reusableWidget'],
    },
    urls: {
        notebooks: (): string => '/notebooks',
        notebook: (shortId: string): string => `/notebooks/${shortId}`,
        canvas: (): string => `/canvas`,
        reusableWidget: (widgetId: string): string => `/notebooks/widgets/${widgetId}`,
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
