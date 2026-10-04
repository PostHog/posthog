import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { FEATURE_FLAGS } from 'lib/constants'
import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { emailTemplaterLogic } from 'scenes/hog-functions/email-templater/emailTemplaterLogic'
import type { EditorRef } from 'scenes/hog-functions/email-templater/emailTemplaterLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { brandedStarterLogic } from './brandedStarterLogic'
import { NEW_TEMPLATE } from './constants'
import { messageTemplateLogic } from './messageTemplateLogic'

jest.mock('lib/lemon-ui/LemonToast', () => ({ lemonToast: { error: jest.fn(), success: jest.fn() } }))

describe('branded starter editor handoff', () => {
    let templateLogic: ReturnType<typeof messageTemplateLogic.build>
    let templater: ReturnType<typeof emailTemplaterLogic.build>
    let starter: ReturnType<typeof brandedStarterLogic.build>
    let editor: {
        addEventListener: jest.Mock
        loadDesign: jest.Mock
        exportHtml: jest.Mock
        exportPlainText: jest.Mock
    }

    beforeEach(() => {
        useMocks({})
        initKeaTests()
        jest.clearAllMocks()
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.EMAIL_BRANDED_STARTER], {
            [FEATURE_FLAGS.EMAIL_BRANDED_STARTER]: true,
        })
        router.actions.push('/workflows/library/templates/new', { mode: 'editor', brandedStarter: 'true' })
        templateLogic = messageTemplateLogic({ id: 'new' })
        templateLogic.mount()
        templater = emailTemplaterLogic({
            value: NEW_TEMPLATE.content.email,
            onChange: jest.fn(),
            type: 'native_email_template',
            layout: 'inline',
        })
        templater.mount()
        let design = NEW_TEMPLATE.content.email.design
        editor = {
            addEventListener: jest.fn(),
            loadDesign: jest.fn((nextDesign) => {
                design = nextDesign
                templater.actions.designLoaded()
            }),
            exportHtml: jest.fn((callback) =>
                callback({ html: '<p>Juniper Studio</p><a href="{{ unsubscribe_url }}">Unsubscribe</a>', design })
            ),
            exportPlainText: jest.fn((callback) => callback({ text: 'Juniper Studio\nUnsubscribe' })),
        }
        templater.actions.setEmailEditorRef({ editor } as unknown as EditorRef)
        templater.actions.onEmailEditorReady()
        starter = brandedStarterLogic({ id: 'new' })
        starter.mount()
        starter.actions.setBrandValues({ name: 'Juniper Studio', primaryColor: '#ffd400' })
    })

    afterEach(() => {
        starter.unmount()
        templater.unmount()
        templateLogic.unmount()
        jest.useRealTimers()
    })

    it('exports an unedited starter before handing an unsaved template to the normal editor', async () => {
        await expectLogic(starter, () => starter.actions.submitBrand()).toDispatchActions(['submitBrandSuccess'])

        expect(templateLogic.values.template).toMatchObject({
            id: 'new',
            name: 'Juniper Studio starter template',
            content: {
                email: { html: expect.stringContaining('Juniper Studio'), text: 'Juniper Studio\nUnsubscribe' },
            },
        })
        expect(templateLogic.values.templateChanged).toBe(true)
        expect(templateLogic.values.templatePickerOpen).toBe(false)
        expect(templateLogic.values.originalTemplate).toEqual(NEW_TEMPLATE)
    })

    it.each(['', '{ }'])('shows only field validation for an empty effective name %j', async (name) => {
        starter.actions.setBrandValue('name', name)
        await expectLogic(starter, () => starter.actions.submitBrand()).toDispatchActions(['submitBrandFailure'])
        expect(templateLogic.values.templateChanged).toBe(false)
        expect(lemonToast.error).not.toHaveBeenCalled()
    })

    it('ignores an expired export callback while a retry waits for its design to load', async () => {
        jest.useFakeTimers()
        let latePlainText!: (data: { text: string }) => void
        editor.exportPlainText.mockImplementationOnce((callback) => {
            latePlainText = callback
        })
        const first = starter.asyncActions.submitBrandRequest(starter.values.brand)
        await jest.advanceTimersByTimeAsync(30001)
        await first
        expect(starter.values.isBrandSubmitting).toBe(false)

        editor.loadDesign.mockImplementationOnce(() => {})
        const retry = starter.asyncActions.submitBrandRequest(starter.values.brand)
        await jest.advanceTimersByTimeAsync(0)
        latePlainText({ text: 'Expired result' })
        templater.actions.designLoaded()
        await jest.advanceTimersByTimeAsync(0)

        expect(starter.values.isBrandSubmitting).toBe(false)
        expect(templateLogic.values.template.content.email.text).toBe('Juniper Studio\nUnsubscribe')
        await retry
    })
})
