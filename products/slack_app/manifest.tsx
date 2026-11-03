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
        '/integrations/slack/:integrationId/setup': ['SlackAppWorkspaceSetup', 'slackAppWorkspaceSetup'],
    },
    redirects: {},
    urls: {
        slackAppWorkspaceSetup: (integrationId: number | string): string =>
            `/integrations/slack/${integrationId}/setup`,
    },
    fileSystemTypes: {},
    treeItemsNew: [],
    treeItemsProducts: [],
}
