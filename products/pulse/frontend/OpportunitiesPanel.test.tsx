import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import { Provider } from 'kea'

import { initKeaTests } from '~/test/init'

import type { OpportunityApi, ProposedExperimentApi } from './generated/api.schemas'
import { OpportunitiesPanel, ProposedExperimentSummary } from './OpportunitiesPanel'
import { pulseLogic } from './pulseLogic'

const baseOpportunity: OpportunityApi = {
    id: 'opp-1',
    kind: 'build',
    status: 'open',
    title: 'Recover the signup drop',
    summary: 's',
    suggested_action: 'a',
    evidence: [],
    goal_relevant: false,
    proposed_experiment: null,
    first_seen_brief: null,
    created_at: '2026-06-01T00:00:00Z',
    created_by: null,
    updated_at: null,
}

const proposedExperiment: ProposedExperimentApi = {
    hypothesis: 'h',
    flag_key_suggestion: 'entry-point',
    target_metric: { insight_short_id: 'abc123' },
    variant_sketch: 'v',
}

describe('OpportunitiesPanel', () => {
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

    it('tags goal-relevant rows with a Goal tag, and only those', () => {
        logic.actions.loadOpportunitiesSuccess([
            { ...baseOpportunity, id: 'opp-goal', title: 'Move the entry point', goal_relevant: true },
            baseOpportunity,
        ])
        render(
            <Provider>
                <OpportunitiesPanel />
            </Provider>
        )
        expect(screen.getAllByText('Goal')).toHaveLength(1)
        expect(screen.getByText('Move the entry point')).toBeInTheDocument()
        expect(screen.getByText('Recover the signup drop')).toBeInTheDocument()
    })

    it.each<[string, OpportunityApi, boolean, boolean]>([
        ['an open row with a proposal', { ...baseOpportunity, proposed_experiment: proposedExperiment }, true, false],
        ['an open row without a proposal', baseOpportunity, false, false],
        [
            'an acted row with a proposal',
            { ...baseOpportunity, status: 'acted', proposed_experiment: proposedExperiment },
            false,
            true,
        ],
        [
            'a resolved row with a proposal',
            { ...baseOpportunity, status: 'resolved', proposed_experiment: proposedExperiment },
            false,
            true,
        ],
    ])('gates the Create experiment button for %s', (_name, opportunity, buttonVisible, tagVisible) => {
        logic.actions.loadOpportunitiesSuccess([opportunity])
        render(
            <Provider>
                <OpportunitiesPanel />
            </Provider>
        )
        expect(screen.queryByText('Create experiment') !== null).toBe(buttonVisible)
        // The proposal outlives the open status as a read-only tag — it must not vanish with the button.
        expect(screen.queryByText('Proposed experiment') !== null).toBe(tagVisible)
    })

    it('offers one acted action for proposal rows: Create experiment replaces Mark as acted', () => {
        logic.actions.loadOpportunitiesSuccess([{ ...baseOpportunity, proposed_experiment: proposedExperiment }])
        render(
            <Provider>
                <OpportunitiesPanel />
            </Provider>
        )
        expect(screen.getByText('Create experiment')).toBeInTheDocument()
        expect(screen.queryByText('Mark as acted')).not.toBeInTheDocument()
        expect(screen.getByText('Dismiss')).toBeInTheDocument()
    })

    it.each<[string, ProposedExperimentApi, boolean]>([
        ['a validated target metric', proposedExperiment, true],
        ['a dropped (null) target metric', { ...proposedExperiment, target_metric: null }, false],
    ])('renders the proposal summary with %s', (_name, proposal, metricVisible) => {
        render(<ProposedExperimentSummary proposal={proposal} />)
        expect(screen.getByText('Hypothesis:')).toBeInTheDocument()
        expect(screen.queryByText('Target metric:') !== null).toBe(metricVisible)
    })
})
