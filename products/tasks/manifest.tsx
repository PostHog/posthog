import { IconBug } from '@posthog/icons'
import { urls } from 'scenes/urls'

import { ProductManifest } from '../../frontend/src/types'

export const manifest: ProductManifest = {
    name: 'Tasks',
    scenes: {
        TaskTracker: {
            name: 'Tasks',
            import: () => import('./frontend/TaskTracker'),
            projectBased: true,
            defaultDocsPath: '/docs/tasks',
            activityScope: 'TaskTracker',
        },
    },
    routes: {
        '/tasks': ['TaskTracker', 'taskTracker'],
    },
    redirects: {},
    urls: {
        taskTracker: (): string => '/tasks',
    },
    fileSystemTypes: {
        task: {
            name: 'Task',
            icon: <IconBug />,
            href: () => urls.taskTracker(),
            iconColor: ['var(--product-tasks-light)', 'var(--product-tasks-dark)'],
            filterKey: 'task',
        },
    },
    treeItemsNew: [],
    treeItemsProducts: [
        {
            path: 'Tasks',
            category: 'Development',
            type: 'task',
            href: urls.taskTracker(),
        },
    ],
}
