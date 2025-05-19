import { IconExternal } from '@posthog/icons'
import { urls } from 'scenes/urls'

import { ProductManifest } from '~/types'

export const manifest: ProductManifest = {
    name: 'Links',
    scenes: {
        Links: {
            name: 'Links',
            import: () => import('./frontend/LinksScene'),
            projectBased: true,
            defaultDocsPath: '/docs/link-tracking',
            activityScope: 'Link',
        },
        Link: {
            name: 'Link',
            import: () => import('./frontend/LinkScene'),
            projectBased: true,
            defaultDocsPath: '/docs/link-tracking',
            activityScope: 'Link',
        },
    },
    routes: {
        '/links': ['Links', 'links'],
        '/link/:id': ['Link', 'link'],
    },
    urls: {
        links: (): string => '/links',
        link:
            /** @param id A UUID or 'new'. ':id' for routing. */
            (id: string): string => `/links/${id}`,
    },
    fileSystemTypes: {
        link: {
            icon: <IconExternal />,
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
            type: 'link',
            href: urls.links(),
        },
    ],
    fileSystemFilterTypes: {
        link: { name: 'Links' },
    },
}
