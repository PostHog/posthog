import { FEATURE_FLAGS } from 'lib/constants'
import { urls } from 'scenes/urls'

import { ProductManifest } from '../../frontend/src/types'

export const manifest: ProductManifest = {
    name: 'Tasks',
    scenes: {
        TaskTracker: {
            name: 'Tasks',
            import: () => import('./frontend/TaskTracker'),
            projectBased: true,
            activityScope: 'TaskTracker',
            description: 'Tasks are work that agents can do for you, like creating a pull request or fixing an issue.',
            iconType: 'task',
        },
        TaskDetail: {
            name: 'Task',
            import: () => import('./frontend/TaskDetailScene'),
            projectBased: true,
            activityScope: 'TaskDetail',
        },
        // Hidden internal debug scene. No nav entry — reachable only by typing the URL.
        SlackTaskContext: {
            name: 'Slack task context',
            import: () => import('./frontend/SlackTaskContextScene'),
            projectBased: true,
        },
    },
    routes: {
        '/tasks': ['TaskTracker', 'taskTracker'],
        '/tasks/:taskId': ['TaskDetail', 'taskDetail'],
        '/slack-task-context': ['SlackTaskContext', 'slackTaskContext'],
    },
    redirects: {},
    urls: {
        taskTracker: (): string => '/tasks',
        taskDetail: (taskId: string | number): string => `/tasks/${taskId}`,
        slackTaskContext: (): string => '/slack-task-context',
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
