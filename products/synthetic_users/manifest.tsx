import { FEATURE_FLAGS } from 'lib/constants'
import { urls } from 'scenes/urls'

import { ProductKey } from '~/queries/schema/schema-general'

import { FileSystemIconColor, ProductManifest } from '../../frontend/src/types'

export const manifest: ProductManifest = {
    name: 'Synthetic users',
    scenes: {
        SyntheticUsers: {
            import: () => import('./frontend/SyntheticUsersScene'),
            projectBased: true,
            name: 'Synthetic users',
            activityScope: 'SyntheticUsers',
            layout: 'app-container',
            iconType: 'cohort',
            description: 'Run UX research with AI-generated users.',
        },
        SyntheticUsersStudy: {
            import: () => import('./frontend/StudyDetailsScene'),
            projectBased: true,
            name: 'Study details',
            activityScope: 'SyntheticUsers',
            layout: 'app-container',
            iconType: 'cohort',
        },
        SyntheticUsersSession: {
            import: () => import('./frontend/SessionDetailScene'),
            projectBased: true,
            name: 'Session details',
            activityScope: 'SyntheticUsers',
            layout: 'app-container',
            iconType: 'cohort',
        },
    },
    routes: {
        '/synthetic-users': ['SyntheticUsers', 'syntheticUsers'],
        '/synthetic-users/:studyId': ['SyntheticUsersStudy', 'syntheticUsersStudy'],
        '/synthetic-users/:studyId/sessions/:sessionId': ['SyntheticUsersSession', 'syntheticUsersSession'],
    },
    urls: {
        syntheticUsers: (): string => '/synthetic-users',
        syntheticUsersStudy: (studyId: string): string => `/synthetic-users/${studyId}`,
        syntheticUsersSession: (studyId: string, sessionId: string): string =>
            `/synthetic-users/${studyId}/sessions/${sessionId}`,
    },
    fileSystemTypes: {},
    treeItemsProducts: [
        {
            path: 'Synthetic users',
            intents: [ProductKey.SYNTHETIC_USERS],
            category: 'Unreleased',
            iconType: 'persons',
            iconColor: ['var(--color-product-persons-light)'] as FileSystemIconColor,
            href: urls.syntheticUsers(),
            flag: FEATURE_FLAGS.SYNTHETIC_USERS,
            tags: ['alpha'],
            sceneKey: 'SyntheticUsers',
        },
    ],
}
