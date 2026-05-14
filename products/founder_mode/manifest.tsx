/**
 * Product manifest for founder_mode.
 *
 * Defines scenes, routes, URLs, and navigation for this product.
 */
import { ProductManifest } from '../../frontend/src/types'

export const manifest: ProductManifest = {
    name: 'FounderMode',
    scenes: {
        FounderMode: {
            name: 'Founder mode',
            import: () => import('./frontend/FounderMode'),
            projectBased: true,
            layout: 'plain',
        },
        FounderModeLayout: {
            name: 'Founder mode',
            import: () => import('./frontend/FounderModeLayout'),
            projectBased: true,
            layout: 'plain',
        },
        FounderModeWorkspace: {
            name: 'Founder workspace',
            import: () => import('./frontend/workspace/FounderModeWorkspace'),
            projectBased: true,
            layout: 'app-raw',
            iconType: 'notebook',
        },
        FounderModeLandingPreview: {
            name: 'Landing page preview',
            import: () => import('./frontend/scenes/FounderModeLandingPreview'),
            projectBased: true,
            layout: 'plain',
        },
        FounderModePostHogStack: {
            name: 'Your PostHog stack',
            import: () => import('./frontend/scenes/FounderModePostHogStack'),
            projectBased: true,
            layout: 'plain',
        },
    },
    routes: {
        '/init': ['FounderMode', 'founderMode'],
        '/founder': ['FounderModeLayout', 'founderModeLayout'],
        '/founder/workspace': ['FounderModeWorkspace', 'founderModeWorkspace'],
        '/founder/workspace/:path': ['FounderModeWorkspace', 'founderModeWorkspace'],
        '/founder/landing-preview': ['FounderModeLandingPreview', 'founderModeLandingPreview'],
        '/founder/posthog-stack': ['FounderModePostHogStack', 'founderModePostHogStack'],
    },
    redirects: {},
    urls: {
        founderMode: (): string => '/init',
        founderModeLayout: (): string => '/founder',
        founderModeWorkspace: (path?: string): string =>
            path ? `/founder/workspace/${encodeURIComponent(path)}` : '/founder/workspace',
        founderModeLandingPreview: (): string => '/founder/landing-preview',
        founderModePostHogStack: (): string => '/founder/posthog-stack',
    },
    fileSystemTypes: {},
    treeItemsNew: [],
    treeItemsProducts: [],
}
