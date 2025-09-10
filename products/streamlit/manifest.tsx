import { urls } from 'scenes/urls'

import { FileSystemIconColor, ProductManifest } from '../../frontend/src/types'

export const manifest: ProductManifest = {
    name: 'Streamlit',
    urls: {
        streamlit: (): string => `/streamlit`,
    },
    fileSystemTypes: {
        streamlit: {
            name: 'Streamlit',
            iconType: 'streamlit',
            href: () => urls.streamlit(),
            iconColor: ['var(--color-product-streamlit-light)'],
            filterKey: 'streamlit',
            // flag: FEATURE_FLAGS.STREAMLIT, // Uncomment when you add the feature flag
        },
    },
    treeItemsProducts: [
        {
            path: 'Streamlit',
            category: 'Tools',
            href: urls.streamlit(),
            type: 'streamlit',
            // flag: FEATURE_FLAGS.STREAMLIT, // Uncomment when you add the feature flag
            tags: ['alpha'],
            iconType: 'streamlit',
            iconColor: ['var(--color-product-streamlit-light)'] as FileSystemIconColor,
        },
    ],
}
