import { Meta, StoryObj } from '@storybook/react'
import { fireEvent, within } from '@testing-library/react'

import { mswDecorator } from '~/mocks/browser'

import type { ScoringConfigApi, ScoringPreviewResponseApi } from '../generated/api.schemas'
import { EnrichmentScoring } from './EnrichmentScoring'

const CONFIG: ScoringConfigApi = {
    id: 'active-formula',
    version: 'v1',
    source: `let ai := if(ai_pilled, 15, 0);
return {
    'status': 'scored',
    'score': 42 + ai,
    'components': {'traction': 22, 'capital': 20, 'ai': ai}
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
            ai_pilled: index % 2 === 0,
            domain: `example-company-${index + 1}.com`,
            company: { description: 'An example software company for previewing the score.' },
        },
        active: {
            status: 'scored',
            dq_reason: null,
            low_confidence: false,
            score: 42,
            components: { traction: 22, capital: 20, ai: 0 },
        },
        preview: {
            status: 'scored',
            dq_reason: null,
            low_confidence: false,
            score: index % 2 === 0 ? 57 : 42,
            components: { traction: 22, capital: 20, ai: index % 2 === 0 ? 15 : 0 },
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
        fireEvent.click(await canvas.findByText('Test 10 companies'))
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
