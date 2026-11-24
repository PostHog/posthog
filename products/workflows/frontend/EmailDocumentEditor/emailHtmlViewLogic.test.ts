import { expectLogic } from 'kea-test-utils'

import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import {
    EmailTemplate,
    EmailTemplaterLogicProps,
    emailTemplaterLogic,
} from 'scenes/hog-functions/email-templater/emailTemplaterLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { emailHtmlViewLogic } from './emailHtmlViewLogic'

const STORED_HTML = '<p>stored {{ person.properties.name }}</p>'
const DESIGN = { body: { rows: [{ id: 'stored' }] } }
const EDITED_DESIGN = { body: { rows: [{ id: 'edited' }] } }

describe('emailHtmlViewLogic', () => {
    let onChange: jest.Mock
    let editorListeners: Record<string, () => void>
    let canvas: { html: string; design: Record<string, any>; broken: boolean }
    let templater: ReturnType<typeof emailTemplaterLogic.build>
    let logic: ReturnType<typeof emailHtmlViewLogic.build>

    const shown = (): { reading: boolean; unsaved: boolean; html?: string } => ({
        reading: logic.values.reading,
        unsaved: templater.values.latestEditUnsaved,
        html: templater.props.value?.html,
    })

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
        logic = emailHtmlViewLogic()
    })

    afterEach(() => {
        logic.unmount()
        templater.unmount()
    })

    it('shows the stored html of an email nobody edited, and writes nothing', async () => {
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        expect(shown()).toEqual({ reading: false, unsaved: false, html: STORED_HTML })
        expect(onChange).not.toHaveBeenCalled()
    })

    it('shows an edit made just before opening, as a save would store it', async () => {
        canvas.design = EDITED_DESIGN
        editorListeners['design:updated']()
        logic.mount()
        await expectLogic(logic).toDispatchActions(['latestEditRead'])

        expect(shown()).toEqual({ reading: false, unsaved: false, html: '<p>fresh render</p>' })
        expect(onChange).toHaveBeenCalledTimes(1)
    })

    it('reports an edit it cannot read instead of passing off the older html as current', async () => {
        canvas.design = EDITED_DESIGN
        canvas.broken = true
        editorListeners['design:updated']()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        expect(shown()).toMatchObject({ reading: false, unsaved: true })

        canvas.broken = false
        logic.actions.readLatestEdit()
        await expectLogic(logic).toFinishAllListeners()
        expect(shown()).toEqual({ reading: false, unsaved: false, html: '<p>fresh render</p>' })
    })
})
