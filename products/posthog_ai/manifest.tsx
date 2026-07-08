import { FEATURE_FLAGS } from 'lib/constants'
import { urls } from 'scenes/urls'

import { ProductManifest } from '../../frontend/src/types'

export const manifest: ProductManifest = {
    name: 'PostHog AI',
    scenes: {
        TaskTracker: {
            name: 'Tasks',
            import: () => import('./frontend/scenes/TaskTracker/TaskTracker'),
            projectBased: true,
            activityScope: 'TaskTracker',
            description: 'Tasks are work that agents can do for you, like creating a pull request or fixing an issue.',
            iconType: 'task',
            // Master/detail with internally-scrolling columns — the scene fills the viewport height.
            layout: 'app-full-scene-height',
        },
    },
    routes: {
        '/tasks': ['TaskTracker', 'taskTracker'],
        // The detail and composer both render inside the TaskTracker scene; the `taskId` param
        // (a UUID, or the reserved value `new`) selects what the right column shows.
        '/tasks/:taskId': ['TaskTracker', 'taskDetail'],
    },
    redirects: {},
    urls: {
        taskTracker: (): string => '/tasks',
        taskDetail: (taskId: string | number): string => `/tasks/${taskId}`,
        taskNew: (): string => '/tasks/new',
    },
    fileSystemTypes: {
        task: {
            name: 'Task',
            iconType: 'task',
            href: () => urls.taskTracker(),
            iconColor: ['var(--product-tasks-light)', 'var(--product-tasks-dark)'],
            filterKey: 'task',
            flag: FEATURE_FLAGS.TASKS,
        },
    },
    treeItemsNew: [],
    treeItemsProducts: [],
}
