import { ProductManifest } from '../../frontend/src/types'

export const manifest: ProductManifest = {
    name: 'Slack app',
    scenes: {
        SlackAppWorkspaceSetup: {
            import: () => import('./frontend/workspace-setup/SlackAppWorkspaceSetupScene'),
            projectBased: true,
            name: 'Slack app setup',
            layout: 'plain',
        },
    },
    routes: {
        '/slack/setup/:integrationId': ['SlackAppWorkspaceSetup', 'slackAppWorkspaceSetup'],
    },
    redirects: {},
    urls: {
        slackAppWorkspaceSetup: (integrationId: number | string): string => `/slack/setup/${integrationId}`,
    },
    fileSystemTypes: {},
    treeItemsNew: [],
    treeItemsProducts: [],
}
