import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import { Provider } from 'kea'

import { initKeaTests } from '~/test/init'

import type { OpportunityApi } from './generated/api.schemas'
import { OpportunitiesPanel } from './OpportunitiesPanel'
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
    first_seen_brief: null,
    created_at: '2026-06-01T00:00:00Z',
    created_by: null,
    updated_at: null,
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
})
