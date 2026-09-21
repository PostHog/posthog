import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { initKeaTests } from '~/test/init'

import type { ToolCallMessage } from '../../../types/toolTypes'
import { type ChatActionComposer, ChatActionComposerProvider } from '../../ChatActionComposerContext'
import { SuggestActionsWidget } from './SuggestActionsWidget'

const ACTIONS = [
    {
        key: 'workflows-create.test-send',
        label: 'Fire a real send to your address',
        kind: 'insert',
        message: 'Send a real test of this workflow to ',
    },
    { key: 'workflows-create.enable', label: 'Enable the workflow', kind: 'run', message: 'Enable workflow wf_1.' },
]

function toolMessage(rawOutput: unknown, status: ToolCallMessage['status'] = 'completed'): ToolCallMessage {
    return {
        id: 'call-1',
        resolvedKey: 'suggest-actions',
        innerToolName: 'suggest-actions',
        rawServerName: 'posthog',
        rawToolName: 'exec',
        rawInput: { command: 'call suggest-actions {}' },
        rawOutput,
        content: [],
        status,
    }
}

const structured = (actions: unknown[], errors: unknown[] = []): unknown => ({
    content: [{ type: 'text', text: 'ok' }],
    structuredContent: { actions, errors },
})

function makeComposer(overrides: Partial<ChatActionComposer> = {}): ChatActionComposer {
    return { insert: jest.fn(), send: jest.fn(), sendDisabledReason: null, ...overrides }
}

function renderWidget(
    message: ToolCallMessage,
    { turnComplete = true, composer }: { turnComplete?: boolean; composer?: ChatActionComposer | null } = {}
): void {
    const widget = <SuggestActionsWidget message={message} isLastInGroup turnComplete={turnComplete} />
    render(composer ? <ChatActionComposerProvider value={composer}>{widget}</ChatActionComposerProvider> : widget)
}

describe('SuggestActionsWidget', () => {
    beforeEach(() => {
        initKeaTests()
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.POSTHOG_AI_CHAT_ACTIONS], {
            [FEATURE_FLAGS.POSTHOG_AI_CHAT_ACTIONS]: true,
        })
    })
    afterEach(cleanup)

    it('renders no buttons when the flag is off, so replayed cards keep the generic display', () => {
        featureFlagLogic.actions.setFeatureFlags([], {})
        renderWidget(toolMessage(structured(ACTIONS)), { composer: makeComposer() })
        expect(screen.queryByText('Enable the workflow')).toBeNull()
    })

    it('renders one button per action and nothing for errors', () => {
        renderWidget(toolMessage(structured(ACTIONS, [{ key: 'workflows-create.nope', reason: 'unknown_action' }])), {
            composer: makeComposer(),
        })
        expect(screen.getByText('Fire a real send to your address')).toBeInTheDocument()
        expect(screen.getByText('Enable the workflow')).toBeInTheDocument()
        expect(screen.queryByText(/unknown_action|nope/)).toBeNull()
    })

    it('insert hands the message to the composer while the turn is still running', () => {
        const composer = makeComposer()
        renderWidget(toolMessage(structured(ACTIONS)), { turnComplete: false, composer })
        fireEvent.click(screen.getByText('Fire a real send to your address'))
        expect(composer.insert).toHaveBeenCalledWith('Send a real test of this workflow to ')
        expect(composer.send).not.toHaveBeenCalled()
    })

    it.each(['send', 'run'])('%s waits for the turn to complete, then sends the message', (kind) => {
        const actions = [{ key: 'workflows-create.x', label: 'Do it', kind, message: 'Do the thing.' }]
        const message = toolMessage(structured(actions))
        const composer = makeComposer()
        renderWidget(message, { turnComplete: false, composer })
        fireEvent.click(screen.getByText('Do it'))
        expect(composer.send).not.toHaveBeenCalled()
        cleanup()

        renderWidget(message, { turnComplete: true, composer })
        fireEvent.click(screen.getByText('Do it'))
        expect(composer.send).toHaveBeenCalledWith('Do the thing.')
        expect(composer.insert).not.toHaveBeenCalled()
    })

    it('keeps send and run disabled while the composer reports a reason, and insert live', () => {
        const composer = makeComposer({ sendDisabledReason: 'Send or clear your draft first' })
        renderWidget(toolMessage(structured(ACTIONS)), { composer })
        fireEvent.click(screen.getByText('Enable the workflow'))
        expect(composer.send).not.toHaveBeenCalled()
        fireEvent.click(screen.getByText('Fire a real send to your address'))
        expect(composer.insert).toHaveBeenCalled()
    })

    it('renders every button disabled when no surface provides a composer', () => {
        renderWidget(toolMessage(structured(ACTIONS)), { composer: null })
        // LemonButton keeps a disabled-with-reason button focusable and marks it aria-disabled.
        expect(screen.getByText('Enable the workflow').closest('button')).toHaveAttribute('aria-disabled', 'true')
        expect(screen.getByText('Fire a real send to your address').closest('button')).toHaveAttribute(
            'aria-disabled',
            'true'
        )
    })

    it('falls back to the generic card while the call is still running or when the payload is malformed', () => {
        renderWidget(toolMessage(structured(ACTIONS), 'in_progress'), { composer: makeComposer() })
        expect(screen.queryByText('Enable the workflow')).toBeNull()
        cleanup()
        renderWidget(toolMessage(structured([{ key: 'k', label: 'Broken', kind: 'open', message: 'x' }])), {
            composer: makeComposer(),
        })
        expect(screen.queryByText('Broken')).toBeNull()
    })
})
