import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'

import { attachedContextLogic } from '~/layout/ai/attachedContextLogic'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { ThreadSkinOverrideContext } from '../../hooks/useThreadSkin'
import { AttachedContextBar } from './AttachedContextBar'
import { AttachedContextChips } from './AttachedContextChips'

describe('AttachedContextBar', () => {
    beforeEach(() => {
        useMocks({})
        initKeaTests()
        attachedContextLogic.mount()
        attachedContextLogic.actions.registerContext('test', [
            { type: 'dashboard', key: 'd1', label: 'Weekly signups' },
            { type: 'email_template', key: 't1', label: 'Welcome series', previewHtml: '<p>Hi</p>' },
        ])
    })

    afterEach(() => {
        cleanup()
        attachedContextLogic.unmount()
    })

    // A preview item that also rendered as a chip would show twice, and one without the strip would lose its image.
    it('shows an item with a preview as an attachment above the chips, not as a chip', () => {
        const { container } = render(<AttachedContextBar />)

        const strip = container.querySelector('[data-attr="posthog-ai-context-attachments"]')
        expect(strip).toHaveTextContent('Welcome series')
        expect(strip?.querySelector('iframe')).toHaveAttribute('title', 'Welcome series preview')
        expect(strip).not.toHaveTextContent('Weekly signups')
        expect(container.querySelectorAll('.LemonTag')).toHaveLength(1)
    })

    // The bar is the only chip row on surfaces with their own composer, so it must follow the skin to keep links.
    it('renders quill chips under the quill skin', () => {
        const { container } = render(
            <ThreadSkinOverrideContext.Provider value="quill">
                <AttachedContextBar />
            </ThreadSkinOverrideContext.Provider>
        )

        expect(container.querySelector('[data-attr="posthog-ai-context-chip"]')).toHaveTextContent('Weekly signups')
        expect(container.querySelectorAll('.LemonTag')).toHaveLength(0)
    })

    // Chips that follow the registry would drop the chat's context on navigation and show the new page instead.
    it('shows a started chat its saved context, not the context of the current page', () => {
        attachedContextLogic.actions.contextDelivered('task-a', [{ type: 'experiment', key: 17, label: 'Checkout' }])

        const { container } = render(<AttachedContextChips taskId="task-a" />)

        expect(container).toHaveTextContent('Checkout')
        expect(container).not.toHaveTextContent('Weekly signups')

        fireEvent.click(container.querySelector('.LemonTag') as Element)

        expect(attachedContextLogic.values.chatChipsByTask['task-a']).toEqual([])
        expect(attachedContextLogic.values.contextItems.map((item) => item.key)).toEqual(['d1', 't1'])
    })

    it('removes the attachment from the context when its remove control is clicked', () => {
        render(<AttachedContextBar />)

        fireEvent.click(screen.getByLabelText('Remove Welcome series'))

        expect(attachedContextLogic.values.contextItems.map((item) => item.key)).toEqual(['d1'])
    })
})
