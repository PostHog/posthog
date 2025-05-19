import { IconRocket } from '@posthog/icons'
import { urls } from 'scenes/urls'

import { ProductManifest } from '../../frontend/src/types'

export const manifest: ProductManifest = {
    name: 'Link',
    scenes: {
        Links: {
            name: 'Links',
            import: () => import('./frontend/LinksScene'),
            projectBased: true,
            defaultDocsPath: '/docs/link',
            activityScope: 'Link',
        },
        Link: {
            name: 'Link',
            import: () => import('./frontend/LinkScene'),
            projectBased: true,
            defaultDocsPath: '/docs/link',
            activityScope: 'Link',
        },
    },
    routes: {
        '/links': ['Links', 'links'],
        '/link/:id': ['Link', 'link'],
    },
    redirects: {},
    urls: {
        links: (): string => `/links`,
        link: (id: string): string => `/link/${id}`,
    },
    fileSystemTypes: {
        link: {
            icon: <IconRocket />,
            href: (ref: string) => urls.link(ref),
        },
    },
    treeItemsNew: [
        {
            path: `Link`,
            type: 'link',
            href: urls.link('new'),
        },
    ],
    treeItemsProducts: [
        {
            path: 'Links',
            type: 'links',
            href: urls.links(),
        },
    ],
    fileSystemFilterTypes: {
        link: { name: 'Link' },
    },
}
