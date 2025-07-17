import { IconBug } from '@posthog/icons'
import { urls } from 'scenes/urls'

import { ProductManifest } from '../../frontend/src/types'

export const manifest: ProductManifest = {
    name: 'Issue Tracker',
    scenes: {
        IssueTracker: {
            name: 'Issue Tracker',
            import: () => import('./frontend/IssueTracker'),
            projectBased: true,
            defaultDocsPath: '/docs/issue-tracker',
            activityScope: 'IssueTracker',
        },
    },
    routes: {
        '/issue_tracker': ['IssueTracker', 'issueTracker'],
    },
    redirects: {},
    urls: {
        issueTracker: (): string => '/issue_tracker',
    },
    fileSystemTypes: {
        issue: {
            name: 'Issue',
            icon: <IconBug />,
            href: () => urls.issueTracker(),
            iconColor: ['var(--product-issue-tracker-light)', 'var(--product-issue-tracker-dark)'],
            filterKey: 'issue',
        },
    },
    treeItemsNew: [],
    treeItemsProducts: [
        {
            path: 'Issue Tracker',
            category: 'Development',
            type: 'issue',
            href: urls.issueTracker(),
        },
    ],
}
