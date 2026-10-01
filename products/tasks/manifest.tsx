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
        TaskSpaces: {
            name: 'Spaces',
            import: () => import('./frontend/spaces/SpacesScene'),
            projectBased: true,
        },
        TaskSpace: {
            name: 'Space',
            import: () => import('./frontend/spaces/SpaceScene'),
            projectBased: true,
        },
        TaskLoop: {
            name: 'Loop',
            import: () => import('./frontend/loops/LoopScene'),
            projectBased: true,
        },
    },
    routes: {
        '/slack-task-context': ['SlackTaskContext', 'slackTaskContext'],
        '/spaces': ['TaskSpaces', 'taskSpaces'],
        '/spaces/:id': ['TaskSpace', 'taskSpace'],
        '/spaces/:id/settings': ['TaskSpace', 'taskSpaceSettings'],
        '/loops/:id': ['TaskLoop', 'taskLoop'],
    },
    redirects: {},
    urls: {
        slackTaskContext: (): string => '/slack-task-context',
        taskSpaces: (): string => '/spaces',
        taskSpace: (id: string): string => `/spaces/${id}`,
        taskSpaceSettings: (id: string): string => `/spaces/${id}/settings`,
        /** Pass `new` to open the form for a new loop. */
        taskLoop: (id: string): string => `/loops/${id}`,
    },
    fileSystemTypes: {},
    treeItemsNew: [],
    treeItemsProducts: [],
}
