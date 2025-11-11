import { actions, kea, path, reducers, selectors } from 'kea'

import { Breadcrumb } from '~/types'

import type { sessionGroupSummariesTableLogicType } from './sessionGroupSummariesTableLogicType'

export interface SessionGroupSummaryListItem {
    session_group_id: string
    name: string
    created_at: string
}

// Mock data
const MOCK_SESSION_GROUP_SUMMARIES: SessionGroupSummaryListItem[] = [
    {
        session_group_id: '1',
        name: 'Session issues Nov 4-6',
        created_at: '2025-11-06T10:00:00Z',
    },
    {
        session_group_id: '2',
        name: 'API failures week 45',
        created_at: '2025-11-05T14:30:00Z',
    },
    {
        session_group_id: '3',
        name: 'User onboarding problems',
        created_at: '2025-11-04T09:15:00Z',
    },
]

export const sessionGroupSummariesTableLogic = kea<sessionGroupSummariesTableLogicType>([
    path(['products', 'session_summaries', 'frontend', 'sessionGroupSummariesTableLogic']),
    actions({
        loadSessionGroupSummaries: true,
    }),
    reducers({
        sessionGroupSummaries: [
            MOCK_SESSION_GROUP_SUMMARIES as SessionGroupSummaryListItem[],
            {
                loadSessionGroupSummaries: () => MOCK_SESSION_GROUP_SUMMARIES,
            },
        ],
    }),
    selectors({
        breadcrumbs: [
            () => [],
            (): Breadcrumb[] => [
                {
                    key: 'session-group-summaries',
                    name: 'Session summaries',
                    iconType: 'insight/hog',
                },
            ],
        ],
    }),
])
