import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { attachedContextLogic } from '../../logics/attachedContextLogic'
import { AttachedContextBar } from './AttachedContextBar'

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

    it('removes the attachment from the context when its remove control is clicked', () => {
        render(<AttachedContextBar />)

        fireEvent.click(screen.getByLabelText('Remove Welcome series'))

        expect(attachedContextLogic.values.contextItems.map((item) => item.key)).toEqual(['d1'])
    })
})
