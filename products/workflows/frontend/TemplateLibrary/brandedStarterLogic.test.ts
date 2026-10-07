import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

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
jest.mock('posthog-js', () => ({ capture: jest.fn() }))

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
        router.actions.push('/workflows/library/templates/new', { brandedStarter: 'true' })
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
        if (starter.isMounted()) {
            starter.unmount()
        }
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

    it.each([
        ['name', ''],
        ['name', '{ }'],
        ['primaryColor', '#12345'],
        ['primaryColor', '#ffd400;background:url(https://example.com/x)'],
        ['logo', new File(['<svg/>'], 'logo.svg', { type: 'image/svg+xml' })],
        ['logo', new File([new Uint8Array(4 * 1024 * 1024)], 'logo.png', { type: 'image/png' })],
    ] as const)('shows only field validation for an invalid %s %#', async (field, value) => {
        starter.actions.setBrandValue(field, value)
        await expectLogic(starter, () => starter.actions.submitBrand()).toDispatchActions(['submitBrandFailure'])
        expect(starter.values.brandValidationErrors[field]).toBeTruthy()
        expect(templateLogic.values.templateChanged).toBe(false)
        expect(lemonToast.error).not.toHaveBeenCalled()
        expect(posthog.capture).not.toHaveBeenCalledWith('email branded starter failed', expect.anything())
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

    it('reuses a logo upload when retrying an export, then omits it when removed', async () => {
        let uploads = 0
        useMocks({
            post: {
                '/api/projects/:team_id/uploaded_media/': () => {
                    uploads++
                    return [201, { image_location: 'https://example.com/juniper.png' }]
                },
            },
        })
        starter.actions.setBrandValue('logo', new File(['logo'], 'logo.png', { type: 'image/png' }))
        editor.loadDesign.mockImplementationOnce(() => {
            throw new Error('Could not load the starter')
        })
        await expectLogic(starter, () => starter.actions.submitBrand()).toDispatchActions(['submitBrandFailure'])
        await expectLogic(starter, () => starter.actions.submitBrand()).toDispatchActions(['submitBrandSuccess'])
        expect(uploads).toBe(1)
        expect(templateLogic.values.template.content.email.design!.body.rows[0].columns[0].contents[0].type).toBe(
            'image'
        )

        starter.actions.setBrandValue('logo', null)
        await expectLogic(starter, () => starter.actions.submitBrand()).toDispatchActions(['submitBrandSuccess'])
        expect(uploads).toBe(1)
        expect(templateLogic.values.template.content.email.design!.body.rows[0].columns[0].contents[0].type).toBe(
            'heading'
        )
    })

    it.each([
        [
            'while the starter exports',
            (): void => {
                editor.loadDesign.mockImplementationOnce(() => {})
            },
        ],
        [
            'while the logo uploads',
            (): void => {
                useMocks({ post: { '/api/projects/:team_id/uploaded_media/': () => new Promise(() => {}) } })
                starter.actions.setBrandValue('logo', new File(['logo'], 'logo.png', { type: 'image/png' }))
            },
        ],
    ])('settles an in-flight submission when the starter is unmounted %s', async (_, stall) => {
        jest.useFakeTimers()
        stall()
        let settled = false
        const submission = starter.asyncActions.submitBrandRequest(starter.values.brand).then(() => {
            settled = true
        })
        starter.unmount()
        await jest.advanceTimersByTimeAsync(0)
        expect(settled).toBe(true)
        expect(lemonToast.error).not.toHaveBeenCalled()
        expect(templateLogic.values.templateChanged).toBe(false)
        await submission
    })

    it('gives a slow logo upload two minutes before restoring the form', async () => {
        jest.useFakeTimers()
        useMocks({
            post: { '/api/projects/:team_id/uploaded_media/': () => new Promise(() => {}) },
        })
        starter.actions.setBrandValue('logo', new File(['logo'], 'logo.png', { type: 'image/png' }))
        let settled = false
        const submission = starter.asyncActions.submitBrandRequest(starter.values.brand).then(() => {
            settled = true
        })
        await jest.advanceTimersByTimeAsync(30001)
        expect(settled).toBe(false)
        await jest.advanceTimersByTimeAsync(90000)
        expect(settled).toBe(true)
        expect(starter.values.isBrandSubmitting).toBe(false)
        expect(lemonToast.error).toHaveBeenCalledWith('Logo upload timed out. Try again.')
        expect(posthog.capture).toHaveBeenCalledWith('email branded starter failed', {
            has_logo: true,
            reason: 'Logo upload timed out. Try again.',
        })
        expect(templateLogic.values.templateChanged).toBe(false)
        await submission
    })
})
