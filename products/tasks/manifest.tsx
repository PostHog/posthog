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
        TaskNewSession: {
            name: 'New session',
            import: () => import('./frontend/spaces/NewSessionScene'),
            projectBased: true,
        },
        TaskSpace: {
            name: 'Space',
            import: () => import('./frontend/spaces/SpaceScene'),
            projectBased: true,
        },
    },
    routes: {
        '/slack-task-context': ['SlackTaskContext', 'slackTaskContext'],
        '/spaces': ['TaskSpaces', 'taskSpaces'],
        // Before `/spaces/:id`, so the router does not read `new` as a space id.
        '/spaces/new': ['TaskNewSession', 'taskNewSession'],
        '/spaces/:id': ['TaskSpace', 'taskSpace'],
        '/spaces/:id/canvases': ['TaskSpace', 'taskSpaceCanvases'],
        '/spaces/:id/new': ['TaskNewSession', 'taskSpaceNewSession'],
        '/spaces/:id/settings': ['TaskSpace', 'taskSpaceSettings'],
    },
    redirects: {},
    urls: {
        slackTaskContext: (): string => '/slack-task-context',
        taskSpaces: (): string => '/spaces',
        taskNewSession: (): string => '/spaces/new',
        taskSpace: (id: string): string => `/spaces/${id}`,
        taskSpaceCanvases: (id: string): string => `/spaces/${id}/canvases`,
        taskSpaceNewSession: (id: string): string => `/spaces/${id}/new`,
        taskSpaceSettings: (id: string): string => `/spaces/${id}/settings`,
    },
    fileSystemTypes: {},
    treeItemsNew: [],
    treeItemsProducts: [],
}
