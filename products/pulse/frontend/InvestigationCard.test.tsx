import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import { Provider } from 'kea'

import { initKeaTests } from '~/test/init'

import type { ProductBriefApi } from './generated/api.schemas'
import { InvestigationCard } from './InvestigationCard'
import { pulseLogic } from './pulseLogic'

const baseBrief = {
    id: 'brief-1',
    config: 'cfg-1',
    status: 'ready',
    trigger: 'on_demand',
    period_days: 7,
    sections: [],
    sources_used: [],
    investigation: [],
    error: null,
    created_at: '2026-07-02T10:00:00Z',
    created_by: null,
    updated_at: null,
} as unknown as ProductBriefApi

describe('InvestigationCard', () => {
    let logic: ReturnType<typeof pulseLogic.build>

    beforeEach(() => {
        initKeaTests()
        logic = pulseLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
        cleanup()
    })

    function renderCard(): void {
        render(
            <Provider>
                <InvestigationCard />
            </Provider>
        )
    }

    it('renders nothing when the brief has no investigation', () => {
        logic.actions.loadBriefDetailSuccess(baseBrief)
        renderCard()
        expect(screen.queryByText('Goal investigation')).toBeNull()
    })

    it('renders numbered findings with their question, result, and expandable HogQL', () => {
        logic.actions.loadBriefDetailSuccess({
            ...baseBrief,
            investigation: [
                {
                    question: 'What is the CTR from the sidebar?',
                    hogql: 'SELECT count() FROM events',
                    result_summary: '0.42',
                    succeeded: true,
                },
            ],
        } as unknown as ProductBriefApi)
        renderCard()
        expect(screen.getByText('Goal investigation')).toBeInTheDocument()
        expect(screen.getByText('Query 1')).toBeInTheDocument()
        expect(screen.getByText('What is the CTR from the sidebar?')).toBeInTheDocument()
        expect(screen.getByText('0.42')).toBeInTheDocument()
        expect(screen.queryByText('failed')).toBeNull()
        // The raw HogQL is present behind the collapse panel.
        expect(screen.getByText('HogQL')).toBeInTheDocument()
    })

    it('renders a replay finding with session citation chips and no HogQL panel', () => {
        logic.actions.loadBriefDetailSuccess({
            ...baseBrief,
            investigation: [
                {
                    question: 'Why did signups drop?',
                    hogql: '',
                    result_summary: 'Watched 12 sessions. Recurring patterns:',
                    succeeded: true,
                    citations: ['session:abc-123'],
                },
            ],
        } as unknown as ProductBriefApi)
        renderCard()
        expect(screen.getByText('Why did signups drop?')).toBeInTheDocument()
        // The session chip links to the replay player (hideRef: the UUID stays out of the label);
        // a replay finding has no HogQL to expand.
        const chip = screen.getByText('Session')
        // Link renders the current project prefix in tests — assert the player path suffix.
        expect(chip.closest('a')?.getAttribute('href')).toContain('/replay/abc-123')
        expect(screen.queryByText('HogQL')).toBeNull()
    })

    it('marks failed steps so a gap is legible, not presented as data', () => {
        logic.actions.loadBriefDetailSuccess({
            ...baseBrief,
            investigation: [
                {
                    question: 'Which pages?',
                    hogql: 'SELECT bad',
                    result_summary: 'Query failed to run (ExposedHogQLError).',
                    succeeded: false,
                },
            ],
        } as unknown as ProductBriefApi)
        renderCard()
        expect(screen.getByText('failed')).toBeInTheDocument()
        expect(screen.getByText('Query failed to run (ExposedHogQLError).')).toBeInTheDocument()
    })
})
