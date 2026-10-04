import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { FEATURE_FLAGS } from 'lib/constants'
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
    beforeEach(() => {
        useMocks({})
        initKeaTests()
    })

    it('exports an unedited starter before handing an unsaved template to the normal editor', async () => {
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.EMAIL_BRANDED_STARTER], {
            [FEATURE_FLAGS.EMAIL_BRANDED_STARTER]: true,
        })
        router.actions.push('/workflows/library/templates/new', { mode: 'editor', brandedStarter: 'true' })
        const templateLogic = messageTemplateLogic({ id: 'new' })
        templateLogic.mount()
        const templater = emailTemplaterLogic({
            value: NEW_TEMPLATE.content.email,
            onChange: jest.fn(),
            type: 'native_email_template',
            layout: 'inline',
        })
        templater.mount()
        let design = NEW_TEMPLATE.content.email.design
        templater.actions.setEmailEditorRef({
            editor: {
                addEventListener: jest.fn(),
                loadDesign: jest.fn((nextDesign) => {
                    design = nextDesign
                    templater.actions.designLoaded()
                }),
                exportHtml: jest.fn((callback) =>
                    callback({ html: '<p>Juniper Studio</p><a href="{{ unsubscribe_url }}">Unsubscribe</a>', design })
                ),
                exportPlainText: jest.fn((callback) => callback({ text: 'Juniper Studio\nUnsubscribe' })),
            },
        } as unknown as EditorRef)
        templater.actions.onEmailEditorReady()
        const starter = brandedStarterLogic({ id: 'new' })
        starter.mount()
        starter.actions.setBrandValues({ name: 'Juniper Studio', primaryColor: '#ffd400' })

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
        starter.unmount()
        templater.unmount()
        templateLogic.unmount()
    })
})
