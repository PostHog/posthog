import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { BindLogic } from 'kea'

import { emailTemplaterLogic } from 'scenes/hog-functions/email-templater/emailTemplaterLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { EmailDocumentEditor } from './EmailDocumentEditor'

jest.mock('./components/EmailStylePanel', () => ({ EmailStylePanel: () => null }))
jest.mock('./components/EmailBlockHandle', () => ({ EmailBlockHandle: () => null }))
jest.mock('./components/EmailSelectionToolbar', () => ({ EmailSelectionToolbar: () => null }))

describe('EmailDocumentEditor', () => {
    afterEach(cleanup)

    it('keeps the scroll position through Preview and back', async () => {
        useMocks({
            get: {
                '/api/environments/:team_id/messaging_templates/': { results: [] },
                '/api/projects/:team_id/property_definitions/': { results: [] },
            },
        })
        initKeaTests()
        global.ResizeObserver = class {
            observe(): void {}
            unobserve(): void {}
            disconnect(): void {}
        } as any
        const value = { design: null, html: '', text: '', subject: '', from: '', to: '' }
        render(
            <BindLogic
                logic={emailTemplaterLogic}
                props={{ value, onChange: jest.fn(), type: 'native_email_template', layout: 'inline' }}
            >
                <EmailDocumentEditor />
            </BindLogic>
        )
        const canvas = await screen.findByTestId('email-editor-scroll')
        canvas.scrollTop = 300
        fireEvent.scroll(canvas)

        fireEvent.click(screen.getByTestId('email-editor-mode-preview'))
        expect(screen.queryByTestId('email-editor-scroll')).not.toBeInTheDocument()
        fireEvent.click(screen.getByTestId('email-editor-mode-edit'))

        expect(screen.getByTestId('email-editor-scroll').scrollTop).toBe(300)
    })
})
