import { Meta, StoryObj } from '@storybook/react'
import { within } from '@testing-library/react'

import { mswDecorator } from '~/mocks/browser'

import type { ScoringConfigApi, ScoringPreviewResponseApi } from '../generated/api.schemas'
import { EnrichmentScoring } from './EnrichmentScoring'
import { enrichmentScoringLogic } from './enrichmentScoringLogic'

const CONFIG: ScoringConfigApi = {
    id: 'active-formula',
    version: 'v1',
    source: `let segment := enrichments.business_model.segment;
let fit := if(segment == 'b2b', 10, 0);
return {
    'status': 'scored',
    'score': 42 + fit,
    'components': {'baseline': 42, 'segment': fit},
    'flags': {
        'segment': segment,
        'review_required': enrichments.business_model.recurring_revenue == 'unknown'
    }
};`,
    is_active: true,
    created_at: '2026-09-21T00:00:00Z',
    created_by_email: 'staff@example.com',
}
const PREVIEW: ScoringPreviewResponseApi = {
    results: Array.from({ length: 10 }, (_, index) => ({
        company: index === 0 ? 'Example company with a longer name' : `Example company ${index + 1}`,
        domain: `example-company-${index + 1}.com`,
        inputs: {
            company: { description: 'An invented company for previewing the score.' },
            signup: { role: 'founder', domain: `example-company-${index + 1}.com`, wizard_ai_sdk: false },
            enrichments: {
                business_model: {
                    segment: index % 2 === 0 ? 'b2b' : 'consumer',
                    recurring_revenue: index % 3 === 0 ? 'unknown' : index % 3 === 1,
                },
            },
            lists: { target_segments: ['b2b'] },
        },
        active: {
            status: 'scored',
            dq_reason: null,
            flags: { segment: index % 2 === 0 ? 'b2b' : 'consumer', review_required: index % 3 === 0 },
            score: index % 2 === 0 ? 52 : 42,
            components: { baseline: 42, segment: index % 2 === 0 ? 10 : 0 },
        },
        preview: {
            status: 'scored',
            dq_reason: null,
            flags: { segment: index % 2 === 0 ? 'b2b' : 'consumer', review_required: index % 3 === 0 },
            score: index % 2 === 0 ? 57 : 42,
            components: { baseline: 42, segment: index % 2 === 0 ? 15 : 0 },
        },
        error: null,
    })),
    summary: { evaluated: 10, changed: 5, errors: 0 },
}

const meta: Meta<typeof EnrichmentScoring> = {
    component: EnrichmentScoring,
    title: 'Products/Growth/Enrichment scoring',
    decorators: [
        mswDecorator({
            get: { '/api/growth_enrichment_scoring/configs/': { results: [CONFIG], default_source: CONFIG.source } },
            post: { '/api/growth_enrichment_scoring/preview/': PREVIEW },
        }),
    ],
}
export default meta

type Story = StoryObj<typeof meta>

export const Editor: Story = {}

export const TenCompanies: Story = {
    play: async ({ canvasElement }) => {
        const canvas = within(canvasElement)
        const previewButton = await canvas.findByText('Test 10 companies')
        enrichmentScoringLogic.actions.setSource(CONFIG.source.replace("'b2b', 10", "'b2b', 15"))
        previewButton.click()
        await canvas.findByText('Example company 10')
    },
}

export const Narrow: Story = {
    ...TenCompanies,
    decorators: [
        (Story) => (
            <div style={{ width: 520 }}>
                <Story />
            </div>
        ),
    ],
}

export const NoConfiguration: Story = {
    decorators: [
        mswDecorator({
            get: { '/api/growth_enrichment_scoring/configs/': { results: [], default_source: CONFIG.source } },
        }),
    ],
}
