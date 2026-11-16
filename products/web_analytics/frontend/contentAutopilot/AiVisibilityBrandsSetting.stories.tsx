import type { Meta, StoryFn } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'

import { mswDecorator } from '~/mocks/browser'

import type { AEOBrandApi } from '../generated/api.schemas'
import { AiVisibilityBrandsSetting } from './AiVisibilityBrandsSetting'

const brand = (id: number, name: string, domain: string, kind: AEOBrandApi['kind']): AEOBrandApi => ({
    id: `00000000-0000-4000-8000-${String(800 + id).padStart(12, '0')}`,
    name,
    domain,
    kind,
    status: 'suggested',
    source: 'citations',
    aliases: [],
    created_at: '2026-11-01T00:00:00Z',
    updated_at: null,
})

const BRANDS: AEOBrandApi[] = [
    brand(1, 'Flagship', 'flagship.example.io', 'unknown'),
    brand(2, 'Forum', 'forum.example.org', 'unknown'),
    { ...brand(3, 'Rival', 'rival.example.org', 'competitor'), aliases: ['Rival Analytics'] },
]

const meta: Meta<typeof AiVisibilityBrandsSetting> = {
    title: 'Products/Web Analytics/Content autopilot/Brands setting',
    component: AiVisibilityBrandsSetting,
    parameters: {
        featureFlags: [FEATURE_FLAGS.WEB_ANALYTICS_CONTENT_AUTOPILOT],
        testOptions: { snapshotBrowsers: [] },
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/aeo_brands/': () => [
                    200,
                    { count: BRANDS.length, next: null, previous: null, results: BRANDS },
                ],
            },
        }),
    ],
}

export default meta

export const ToReview: StoryFn<typeof AiVisibilityBrandsSetting> = () => (
    <div className="p-4 max-w-200">
        <AiVisibilityBrandsSetting />
    </div>
)
