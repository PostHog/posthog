import { Meta, StoryObj } from '@storybook/react'

import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'
import { EarlyAccessFeatureType } from '~/types'

const EARLY_ACCESS_FEATURE_RESULT = [
    {
        id: '0187c22c-06d9-0000-34fe-daa2e2afb503',
        feature_flag: {
            id: 7,
            team_id: 1,
            name: '',
            key: 'early-access-feature',
            filters: {
                groups: [
                    {
                        variant: null,
                        properties: [],
                        rollout_percentage: null,
                    },
                    {
                        properties: [
                            {
                                key: '$feature_enrollment/early-access-feature',
                                type: 'person',
                                value: ['true'],
                                operator: 'exact',
                            },
                        ],
                        rollout_percentage: 100,
                    },
                    {
                        properties: [
                            {
                                key: '$feature_enrollment/early-access-feature',
                                type: 'person',
                                value: ['true'],
                                operator: 'exact',
                            },
                        ],
                        rollout_percentage: 100,
                    },
                ],
                payloads: {},
                multivariate: null,
            },
            deleted: false,
            active: true,
            ensure_experience_continuity: false,
        },
        name: 'dddd',
        description: 'dedd',
        stage: 'alpha',
        documentation_url: '',
        created_at: '2023-04-27T10:04:37.977401Z',
    },
    {
        id: '0187c279-bcae-0000-34f5-4f121921f005',
        feature_flag: {
            id: 6,
            team_id: 1,
            name: '',
            key: 'ww',
            filters: {
                groups: [
                    {
                        variant: null,
                        properties: [
                            {
                                key: '$browser',
                                type: 'person',
                                value: ['Chrome'],
                                operator: 'exact',
                            },
                        ],
                        rollout_percentage: 0,
                    },
                    {
                        properties: [
                            {
                                key: '$feature_enrollment/ww',
                                type: 'person',
                                value: ['true'],
                                operator: 'exact',
                            },
                        ],
                        rollout_percentage: 100,
                    },
                ],
                payloads: {},
                multivariate: null,
            },
            deleted: false,
            active: true,
            ensure_experience_continuity: false,
        },
        name: 'ello',
        description: '',
        stage: 'alpha',
        documentation_url: '',
        created_at: '2023-04-27T11:29:30.798968Z',
    },
]

const meta: Meta = {
    component: App,
    title: 'Scenes-App/Features',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2023-01-28', // To stabilize relative dates
        pageUrl: urls.earlyAccessFeatures(),
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/early-access-feature': {
                    count: 2,
                    results: EARLY_ACCESS_FEATURE_RESULT as any[],
                    next: null,
                    previous: null,
                },
                '/api/projects/:team_id/early-access-feature/not-found/': [
                    404,
                    {
                        detail: 'Not found.',
                    },
                ],
                '/api/projects/:team_id/early-access-feature/:flagId/':
                    EARLY_ACCESS_FEATURE_RESULT[0] as EarlyAccessFeatureType,
            },
        }),
    ],
}
export default meta

type Story = StoryObj<typeof meta>
export const FeaturesList: Story = {}

export const NewFeatureFlag: Story = {
    parameters: {
        pageUrl: urls.earlyAccessFeature('new'),
    },
}

export const NotFoundEarlyAccess: Story = {
    parameters: {
        pageUrl: urls.earlyAccessFeature('not-found'),
    },
}
