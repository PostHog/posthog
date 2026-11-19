import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'

import { initKeaTests } from '~/test/init'

import { scoutAiLogic } from '../../../logics/scoutAiLogic'
import { ScoutAiPanel } from './ScoutAiPanel'

// Mirrors the runner's own fallback: with no composer supplied it renders the generic task composer.
jest.mock('products/posthog_ai/frontend/api/runner', () => ({
    SidePanelRunner: ({ composer }: { composer?: React.ReactNode }) => (
        <div>{composer ?? <div data-attr="generic-task-composer" />}</div>
    ),
}))

describe('ScoutAiPanel', () => {
    let logic: ReturnType<typeof scoutAiLogic.build>

    beforeEach(() => {
        initKeaTests()
        logic = scoutAiLogic()
        logic.mount()
    })

    afterEach(() => {
        cleanup()
        logic.unmount()
    })

    it('offers a way back instead of the generic composer when the scout is gone', () => {
        // A reload keeps the `inbox-scout` panel option in the URL but not the scout it was about.
        render(<ScoutAiPanel panelId="panel" />)

        expect(screen.getByText('No scout selected')).toBeInTheDocument()
        expect(screen.queryByTestId('generic-task-composer')).not.toBeInTheDocument()
    })
})
