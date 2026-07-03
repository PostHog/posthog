import '@testing-library/jest-dom'

import { fireEvent, render, screen } from '@testing-library/react'

import type { ToolCallMessage } from 'products/posthog_ai/frontend/types/toolTypes'

import { ToolActivity } from './ToolActivity'

function makeMessage(overrides: Partial<ToolCallMessage> = {}): ToolCallMessage {
    return {
        id: 'tc-1',
        resolvedKey: 'Bash',
        rawServerName: 'claude',
        rawToolName: '',
        rawInput: {},
        content: [],
        status: 'completed',
        ...overrides,
    }
}

describe('ToolActivity', () => {
    it('renders the title and subtitle (second line)', () => {
        render(<ToolActivity message={makeMessage()} title="Terminal" subtitle="ls -la" />)
        expect(screen.getByText('Terminal')).toBeInTheDocument()
        expect(screen.getByText('ls -la')).toBeInTheDocument()
    })

    it('keeps the body collapsed once completed and expands on click', () => {
        render(<ToolActivity message={makeMessage()} title="Terminal" body={<div>command output</div>} />)
        expect(screen.queryByText('command output')).not.toBeInTheDocument()
        fireEvent.click(screen.getByRole('button'))
        expect(screen.getByText('command output')).toBeInTheDocument()
    })

    it('auto-expands the body while the tool is running', () => {
        render(
            <ToolActivity
                message={makeMessage({ status: 'in_progress' })}
                title="Terminal"
                body={<div>streaming…</div>}
            />
        )
        expect(screen.getByText('streaming…')).toBeInTheDocument()
    })

    it('renders children always-visible without expanding', () => {
        render(
            <ToolActivity message={makeMessage()} title="Insight">
                <div>the visualization</div>
            </ToolActivity>
        )
        expect(screen.getByText('the visualization')).toBeInTheDocument()
    })

    it('surfaces the failure message', () => {
        render(
            <ToolActivity
                message={makeMessage({ status: 'failed', error: { message: 'boom' } })}
                title="Terminal"
                body={<div>partial</div>}
            />
        )
        expect(screen.getByText('boom')).toBeInTheDocument()
    })

    it('marks a turn-cancelled tool', () => {
        render(<ToolActivity message={makeMessage({ status: 'in_progress' })} title="Terminal" turnCancelled />)
        expect(screen.getByText('(cancelled)')).toBeInTheDocument()
    })
})
