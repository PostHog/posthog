import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { expectLogic } from 'kea-test-utils'

import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import {
    EmailTemplate,
    EmailTemplaterLogicProps,
    emailTemplaterLogic,
} from 'scenes/hog-functions/email-templater/emailTemplaterLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { emailHtmlViewLogic } from '../emailHtmlViewLogic'
import { EmailHtmlView } from './EmailHtmlView'

jest.mock('lib/monaco/CodeEditor', () => ({
    CodeEditor: ({ value }: { value: string }) => <pre data-attr="code">{value}</pre>,
}))

const STORED_HTML = '<p>stored {{ person.properties.name }}</p>'
const DESIGN = { body: { rows: [{ id: 'stored' }] } }

describe('EmailHtmlView', () => {
    let onChange: jest.Mock
    let editorListeners: Record<string, () => void>
    let canvas: { html: string; design: Record<string, any>; broken: boolean }
    let templater: ReturnType<typeof emailTemplaterLogic.build>

    const shown = (): string | null => screen.queryByTestId('code')?.textContent ?? null
    const opened = async (): Promise<void> => {
        render(<EmailHtmlView />)
        await act(() => expectLogic(emailHtmlViewLogic).toDispatchActions(['latestEditRead']))
    }
    const edit = (html: string): void => {
        canvas.html = html
        canvas.design = { body: { rows: [{ id: html }] } }
        editorListeners['design:updated']()
    }

    beforeEach(async () => {
        useMocks({
            get: {
                '/api/environments/:team_id/messaging_templates/': { results: [] },
                '/api/projects/:team_id/property_definitions/': { results: [] },
            },
        })
        initKeaTests()
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([], { 'workflows-email-document-editor': true })
        editorListeners = {}
        canvas = { html: '<p>fresh render</p>', design: DESIGN, broken: false }
        const props = (value: EmailTemplate): EmailTemplaterLogicProps => ({
            value,
            onChange,
            type: 'native_email_template',
            layout: 'inline',
        })
        onChange = jest.fn((value) => emailTemplaterLogic(props(value)))
        templater = emailTemplaterLogic(
            props({ html: STORED_HTML, text: 'stored', design: DESIGN, subject: '', from: '', to: '' })
        )
        templater.mount()
        templater.actions.setEmailEditorRef({
            editor: {
                loadDesign: jest.fn(),
                addEventListener: (event: string, listener: () => void) => {
                    editorListeners[event] = listener
                },
                exportHtml: (callback: (data: any) => void) => {
                    if (canvas.broken) {
                        throw new Error('export failed')
                    }
                    callback({ html: canvas.html, design: canvas.design })
                },
                exportPlainText: (callback: (data: any) => void) => callback({ text: 'text' }),
            },
        } as any)
        templater.actions.onEmailEditorReady()
        editorListeners['design:loaded']()
        await expectLogic(templater).toFinishAllListeners()
    })

    afterEach(() => {
        cleanup()
        templater.unmount()
    })

    it('shows the stored html of an email nobody edited, and writes nothing', async () => {
        await opened()

        expect(shown()).toBe(STORED_HTML)
        expect(onChange).not.toHaveBeenCalled()
    })

    it('shows an edit made just before opening, and one made while open, as a save would store them', async () => {
        edit('<p>just before</p>')
        await opened()
        expect(shown()).toBe('<p>just before</p>')

        act(() => edit('<p>while open</p>'))
        expect(shown()).toBeNull()
        await waitFor(() => expect(shown()).toBe('<p>while open</p>'))
    })

    it('says so when it cannot read the latest edit, instead of showing the older html', async () => {
        canvas.broken = true
        edit('<p>fresh</p>')
        await opened()
        expect(shown()).toBeNull()
        expect(screen.getByText(/Couldn't read your latest change/)).toBeTruthy()

        canvas.broken = false
        fireEvent.click(screen.getAllByText('Try again')[0])
        await waitFor(() => expect(shown()).toBe('<p>fresh</p>'))
    })
})
