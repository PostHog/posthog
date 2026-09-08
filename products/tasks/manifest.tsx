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
        // Hidden too, behind the task-analysis rollout flag. Settings and a run explorer for the
        // PostHog-funded analysis runs.
        TaskAnalysis: {
            name: 'Task analysis',
            import: () => import('./frontend/TaskAnalysisScene'),
            projectBased: true,
        },
    },
    routes: {
        '/slack-task-context': ['SlackTaskContext', 'slackTaskContext'],
        '/task-analysis/runs': ['TaskAnalysis', 'taskAnalysisRuns'],
        '/task-analysis/settings': ['TaskAnalysis', 'taskAnalysisSettings'],
    },
    redirects: {
        '/task-analysis': '/task-analysis/runs',
    },
    urls: {
        slackTaskContext: (): string => '/slack-task-context',
        taskAnalysisRuns: (): string => '/task-analysis/runs',
        taskAnalysisSettings: (): string => '/task-analysis/settings',
    },
    fileSystemTypes: {},
    treeItemsNew: [],
    treeItemsProducts: [],
}
