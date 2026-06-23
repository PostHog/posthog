import '@testing-library/jest-dom'

import { fireEvent, render, screen } from '@testing-library/react'

import type { SandboxToolCallMessage } from 'products/posthog_ai/frontend/sandbox/types/sandboxToolTypes'

import { SandboxToolActivity } from './SandboxToolActivity'

function makeMessage(overrides: Partial<SandboxToolCallMessage> = {}): SandboxToolCallMessage {
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

describe('SandboxToolActivity', () => {
    it('renders the title and subtitle (second line)', () => {
        render(<SandboxToolActivity message={makeMessage()} title="Terminal" subtitle="ls -la" />)
        expect(screen.getByText('Terminal')).toBeInTheDocument()
        expect(screen.getByText('ls -la')).toBeInTheDocument()
    })

    it('keeps the body collapsed once completed and expands on click', () => {
        render(<SandboxToolActivity message={makeMessage()} title="Terminal" body={<div>command output</div>} />)
        expect(screen.queryByText('command output')).not.toBeInTheDocument()
        fireEvent.click(screen.getByRole('button'))
        expect(screen.getByText('command output')).toBeInTheDocument()
    })

    it('auto-expands the body while the tool is running', () => {
        render(
            <SandboxToolActivity
                message={makeMessage({ status: 'in_progress' })}
                title="Terminal"
                body={<div>streaming…</div>}
            />
        )
        expect(screen.getByText('streaming…')).toBeInTheDocument()
    })

    it('renders children always-visible without expanding', () => {
        render(
            <SandboxToolActivity message={makeMessage()} title="Insight">
                <div>the visualization</div>
            </SandboxToolActivity>
        )
        expect(screen.getByText('the visualization')).toBeInTheDocument()
    })

    it('surfaces the failure message', () => {
        render(
            <SandboxToolActivity
                message={makeMessage({ status: 'failed', error: { message: 'boom' } })}
                title="Terminal"
                body={<div>partial</div>}
            />
        )
        expect(screen.getByText('boom')).toBeInTheDocument()
    })

    it('marks a turn-cancelled tool', () => {
        render(<SandboxToolActivity message={makeMessage({ status: 'in_progress' })} title="Terminal" turnCancelled />)
        expect(screen.getByText('(cancelled)')).toBeInTheDocument()
    })
})
