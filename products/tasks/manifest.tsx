import { ProductManifest } from '../../frontend/src/types'

export const manifest: ProductManifest = {
    name: 'Tasks',
    scenes: {
        // Hidden internal debug scene. No nav entry — reachable only by typing the URL.
        SlackTaskContext: {
            name: 'Slack task context',
            import: () => import('./frontend/SlackTaskContextScene'),
            projectBased: true,
        },
    },
    routes: {
        '/slack-task-context': ['SlackTaskContext', 'slackTaskContext'],
    },
    redirects: {},
    urls: {
        slackTaskContext: (): string => '/slack-task-context',
    },
    fileSystemTypes: {},
    treeItemsNew: [],
    treeItemsProducts: [],
}
