import { FEATURE_FLAGS } from 'lib/constants'
import { urls } from 'scenes/urls'

import { FileSystemIconType } from '~/queries/schema/schema-general'
import { FileSystemIconColor, ProductManifest } from '~/types'

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
            name: 'Link',
            iconType: 'link' as FileSystemIconType,
            href: (ref: string) => urls.link(ref),
            iconColor: ['var(--color-product-links-light)'],
            filterKey: 'link',
            flag: FEATURE_FLAGS.LINKS,
        },
    },
    treeItemsNew: [
        {
            path: `Link`,
            type: 'link',
            href: urls.link('new'),
            iconType: 'link' as FileSystemIconType,
            iconColor: ['var(--color-product-links-light)'] as FileSystemIconColor,
            flag: FEATURE_FLAGS.LINKS,
        },
    ],
    treeItemsProducts: [
        {
            path: 'Links',
            category: 'Tools',
            type: 'link',
            href: urls.links(),
            flag: FEATURE_FLAGS.LINKS,
            tags: ['alpha'],
        },
    ],
}
