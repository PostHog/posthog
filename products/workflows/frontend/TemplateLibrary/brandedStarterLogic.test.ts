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
import { detectedBrandLogic } from './detectedBrandLogic'
import { messageTemplateLogic } from './messageTemplateLogic'
import { savedBrandLogic } from './savedBrandLogic'

jest.mock('lib/lemon-ui/LemonToast', () => ({ lemonToast: { error: jest.fn(), success: jest.fn() } }))
jest.mock('posthog-js', () => ({ capture: jest.fn() }))

const SAVED_BRAND_URL = '/api/projects/:team_id/email_brand/current/'

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
    let savedBrands: Record<string, unknown>[]

    beforeEach(async () => {
        savedBrands = []
        useMocks({
            get: { [SAVED_BRAND_URL]: () => [404, { detail: 'This project has no saved Email brand yet.' }] },
            patch: {
                [SAVED_BRAND_URL]: async ({ request }) => {
                    const saved = (await request.json()) as Record<string, unknown>
                    savedBrands.push(saved)
                    return [200, { id: 'brand-id', ...saved }]
                },
            },
        })
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
        await expectLogic(savedBrandLogic).toDispatchActions(['loadSavedBrandSuccess'])
        await expectLogic(detectedBrandLogic).toDispatchActions(['loadDetectedBrandSuccess'])
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
        expect(savedBrands).toEqual([
            { name: 'Juniper Studio', primary_color: '#ffd400', logo_url: null, source: 'manual' },
        ])
    })

    it.each([
        [500, { detail: 'Server error' }, 'Could not save your brand. Try again.'],
        [
            403,
            { detail: 'You do not have editor access to this resource.' },
            'You do not have editor access to this resource.',
        ],
    ])('stops before building the starter when the brand cannot be saved (%s)', async (status, body, toast) => {
        useMocks({ patch: { [SAVED_BRAND_URL]: () => [status, body] } })
        editor.loadDesign.mockClear()

        await expectLogic(starter, () => starter.actions.submitBrand()).toDispatchActions(['submitBrandFailure'])

        expect(editor.loadDesign).not.toHaveBeenCalled()
        expect(templateLogic.values.templateChanged).toBe(false)
        expect(lemonToast.error).toHaveBeenCalledWith(toast)
    })

    it('loads the saved brand when the starter opens after the flag arrived late', async () => {
        starter.unmount()
        featureFlagLogic.actions.setFeatureFlags([], {})
        savedBrandLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.EMAIL_BRANDED_STARTER], {
            [FEATURE_FLAGS.EMAIL_BRANDED_STARTER]: true,
        })

        starter = brandedStarterLogic({ id: 'new' })
        starter.mount()
        expect(starter.values.savedBrandBlockReason).toBe('Loading your saved brand')
        await expectLogic(savedBrandLogic).toDispatchActions(['loadSavedBrandSuccess'])

        expect(starter.values.savedBrandBlockReason).toBeNull()
        savedBrandLogic.unmount()
    })

    it('ignores a saved-brand answer that arrives after a newer one', async () => {
        starter.unmount()
        let failStaleRequest!: (response: [number, Record<string, string>]) => void
        useMocks({ get: { [SAVED_BRAND_URL]: () => new Promise((resolve) => (failStaleRequest = resolve)) } })
        starter = brandedStarterLogic({ id: 'new' })
        starter.mount()
        starter.unmount()
        useMocks({ get: { [SAVED_BRAND_URL]: () => [404, { detail: 'This project has no saved Email brand yet.' }] } })
        starter = brandedStarterLogic({ id: 'new' })
        starter.mount()
        await expectLogic(savedBrandLogic).toDispatchActions(['loadSavedBrandSuccess'])

        failStaleRequest([500, { detail: 'Server error' }])
        await expectLogic(savedBrandLogic).toFinishAllListeners()

        expect(starter.values.savedBrandBlockReason).toBeNull()
    })

    it.each([
        [500, { detail: 'Server error' }, { message: 'Could not load your saved brand.', retryable: true }],
        [
            403,
            { detail: 'You do not have viewer access to this resource.' },
            { message: 'You do not have viewer access to this resource.', retryable: false },
        ],
    ])('never falls back to the website when the saved brand fails to load (%s)', async (status, body, loadError) => {
        starter.unmount()
        useMocks({
            get: { [SAVED_BRAND_URL]: () => [status, body] },
            ...answeringDetection(detectedJuniper),
        })
        starter = brandedStarterLogic({ id: 'new' })
        starter.mount()
        await loadDetection()
        await expectLogic(savedBrandLogic).toFinishAllListeners()

        expect(starter.values.brand).toEqual({ name: '', primaryColor: '#1d4aff', logo: null })
        expect(savedBrandLogic.values.savedBrandLoadError).toEqual(loadError)
        expect(starter.values.savedBrandBlockReason).toBe('Could not load your saved brand')
        starter.actions.setBrandValues({ name: 'Juniper Studio', primaryColor: '#2e7d32' })
        await expectLogic(starter, () => starter.actions.submitBrand()).toDispatchActions(['submitBrandFailure'])
        expect(savedBrands).toEqual([])
        expect(templateLogic.values.templateChanged).toBe(false)
        starter.actions.resetBrand()

        useMocks({ get: { [SAVED_BRAND_URL]: () => [404, { detail: 'This project has no saved Email brand yet.' }] } })
        await expectLogic(savedBrandLogic, () => savedBrandLogic.actions.loadSavedBrand()).toDispatchActions([
            'loadSavedBrandSuccess',
        ])

        expect(starter.values.savedBrandBlockReason).toBeNull()
        expect(starter.values.prefilledFrom).toBe('website')
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
        expect(savedBrands.at(-1)).toMatchObject({ logo_url: 'https://example.com/juniper.png' })

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
            logo_source: 'upload',
            brand_detection: 'none',
            prefilled_from: 'none',
            prefilled: false,
            edited_prefill: false,
            reason: 'Logo upload timed out. Try again.',
        })
        expect(templateLogic.values.templateChanged).toBe(false)
        await submission
    })

    const detectedJuniper = {
        website: 'https://juniper.example/',
        name: 'Juniper Studio',
        primary_color: '#2e7d32',
        logo_url: 'https://app.example.com/uploaded_media/juniper-logo',
    }

    const answeringDetection = (brand: Record<string, string | null>): Parameters<typeof useMocks>[0] => ({
        post: { '/api/projects/:team_id/messaging_templates/detect_brand/': () => [200, brand] },
    })

    async function loadDetection(): Promise<void> {
        await expectLogic(detectedBrandLogic, () => detectedBrandLogic.actions.loadDetectedBrand()).toDispatchActions([
            'loadDetectedBrandSuccess',
        ])
    }

    it('prefills an untouched form and builds the starter around the hosted website logo', async () => {
        let uploads = 0
        useMocks({
            post: { '/api/projects/:team_id/uploaded_media/': () => [201, { image_location: `${uploads++}` }] },
        })
        starter.actions.resetBrand()

        useMocks(answeringDetection(detectedJuniper))
        await loadDetection()

        expect(starter.values.brand).toEqual({
            name: 'Juniper Studio',
            primaryColor: '#2e7d32',
            logo: 'https://app.example.com/uploaded_media/juniper-logo',
        })
        expect(starter.values.brandChanged).toBe(false)
        expect(starter.values.prefilledFromHost).toBe('juniper.example')
        await expectLogic(starter, () => starter.actions.submitBrand()).toDispatchActions(['submitBrandSuccess'])
        expect(uploads).toBe(0)
        expect(
            templateLogic.values.template.content.email.design!.body.rows[0].columns[0].contents[0].values.src
        ).toMatchObject({ url: 'https://app.example.com/uploaded_media/juniper-logo' })
        expect(posthog.capture).toHaveBeenCalledWith('email branded starter generated', {
            has_logo: true,
            logo_source: 'website',
            brand_detection: 'found',
            prefilled_from: 'website',
            prefilled: true,
            edited_prefill: false,
        })
        expect(savedBrands).toEqual([
            {
                name: 'Juniper Studio',
                primary_color: '#2e7d32',
                logo_url: 'https://app.example.com/uploaded_media/juniper-logo',
                source: 'website',
            },
        ])
    })

    it.each([
        [
            'fills the form from the saved brand instead of the website',
            [200, { name: 'Juniper', primary_color: '#123456', logo_url: null, source: 'github' }],
            { name: 'Juniper', primaryColor: '#123456', logo: null },
            'saved',
            'github',
        ],
        [
            'falls back to the website once it knows there is no saved brand',
            [404, { detail: 'This project has no saved Email brand yet.' }],
            {
                name: 'Juniper Studio',
                primaryColor: '#2e7d32',
                logo: 'https://app.example.com/uploaded_media/juniper-logo',
            },
            'website',
            'website',
        ],
    ] as const)(
        '%s, waiting for the saved brand first',
        async (_, savedBrandResponse, expectedBrand, prefilledFrom, source) => {
            starter.unmount()
            let answerSavedBrand!: (response: typeof savedBrandResponse) => void
            useMocks({
                get: { [SAVED_BRAND_URL]: () => new Promise((resolve) => (answerSavedBrand = resolve)) },
                ...answeringDetection(detectedJuniper),
            })
            starter = brandedStarterLogic({ id: 'new' })
            starter.mount()
            await loadDetection()
            expect(starter.values.brand).toEqual({ name: '', primaryColor: '#1d4aff', logo: null })
            expect(starter.values.savedBrandBlockReason).toBe('Loading your saved brand')

            answerSavedBrand(savedBrandResponse)
            await expectLogic(savedBrandLogic).toDispatchActions(['loadSavedBrandSuccess'])

            expect(starter.values.brand).toEqual(expectedBrand)
            expect(starter.values.brandChanged).toBe(false)
            expect(starter.values.prefilledFrom).toBe(prefilledFrom)
            await expectLogic(starter, () => starter.actions.submitBrand()).toDispatchActions(['submitBrandSuccess'])
            expect(savedBrands).toEqual([expect.objectContaining({ source })])
            expect(posthog.capture).toHaveBeenCalledWith(
                'email branded starter generated',
                expect.objectContaining({ prefilled_from: prefilledFrom })
            )
        }
    )

    it('fills only what it detected', async () => {
        starter.actions.resetBrand()
        useMocks(answeringDetection({ ...detectedJuniper, primary_color: null, logo_url: null }))
        await loadDetection()
        expect(starter.values.brand).toEqual({ name: 'Juniper Studio', primaryColor: '#1d4aff', logo: null })
        expect(starter.values.brandDetectionOutcome).toBe('partial')
    })

    it.each([
        ['name', 'Juniper'],
        ['name', ''],
        ['primaryColor', '#1d4aff'],
    ] as const)('keeps the %s the user set to "%s" before detection arrived', async (field, value) => {
        starter.actions.resetBrand()
        starter.actions.setBrandValue(field, value)
        useMocks(answeringDetection(detectedJuniper))
        await loadDetection()
        expect(starter.values.brand[field]).toBe(value)
        expect(starter.values.brand.logo).toBe(detectedJuniper.logo_url)
    })

    it('does not claim a fill when detection only found what the user already typed', async () => {
        starter.actions.resetBrand()
        starter.actions.setBrandValue('name', 'Juniper')
        useMocks(answeringDetection({ ...detectedJuniper, primary_color: null, logo_url: null }))
        await loadDetection()
        expect(starter.values.prefilledFromHost).toBeNull()
    })

    it('leaves the form alone when detection lands while the starter generates', async () => {
        editor.loadDesign.mockImplementationOnce(() => {})
        const submission = starter.asyncActions.submitBrandRequest(starter.values.brand)
        useMocks(answeringDetection(detectedJuniper))
        await loadDetection()
        expect(starter.values.brand).toEqual({ name: 'Juniper Studio', primaryColor: '#ffd400', logo: null })
        starter.unmount()
        await submission
    })

    it('reports an edit to a prefilled field', async () => {
        starter.actions.resetBrand()
        useMocks(answeringDetection(detectedJuniper))
        await loadDetection()
        starter.actions.setBrandValue('primaryColor', '#f54e00')
        await expectLogic(starter, () => starter.actions.submitBrand()).toDispatchActions(['submitBrandSuccess'])
        expect(posthog.capture).toHaveBeenCalledWith(
            'email branded starter generated',
            expect.objectContaining({ prefilled: true, edited_prefill: true })
        )
    })
    describe('detecting from a GitHub repository', () => {
        const GITHUB_DETECTION_URL = '/api/projects/:team_id/email_brand/detect_from_github/'
        const githubJuniper = {
            repository: 'juniper/studio',
            name: 'Juniper Cloud',
            primary_color: '#2e7d32',
            logo_url: 'https://app.example.com/uploaded_media/juniper-logo',
        }

        function answeringGitHub(status: number, body: Record<string, unknown>): Parameters<typeof useMocks>[0] {
            return { post: { [GITHUB_DETECTION_URL]: () => [status, body] } }
        }

        it('fills the form from the repository and saves it as a GitHub brand', async () => {
            useMocks(answeringGitHub(200, githubJuniper))

            await expectLogic(starter, () =>
                starter.actions.detectBrandFromGitHub(7, 'juniper/studio')
            ).toDispatchActions(['detectBrandFromGitHubSuccess'])
            expect(starter.values.brand).toEqual({
                name: 'Juniper Cloud',
                primaryColor: '#2e7d32',
                logo: 'https://app.example.com/uploaded_media/juniper-logo',
            })
            expect(starter.values.prefilledFromHost).toBe('juniper/studio')
            expect(posthog.capture).toHaveBeenCalledWith('email brand github detection', { outcome: 'found' })

            await expectLogic(starter, () => starter.actions.submitBrand()).toDispatchActions(['submitBrandSuccess'])
            expect(savedBrands.at(-1)).toEqual({
                name: 'Juniper Cloud',
                primary_color: '#2e7d32',
                logo_url: 'https://app.example.com/uploaded_media/juniper-logo',
                source: 'github',
            })
            expect(posthog.capture).toHaveBeenCalledWith(
                'email branded starter generated',
                expect.objectContaining({ prefilled_from: 'github', logo_source: 'github' })
            )
        })

        it('keeps the fields the repository had no value for', async () => {
            useMocks(answeringGitHub(200, { ...githubJuniper, primary_color: null, logo_url: null }))

            await expectLogic(starter, () =>
                starter.actions.detectBrandFromGitHub(7, 'juniper/studio')
            ).toDispatchActions(['detectBrandFromGitHubSuccess'])

            expect(starter.values.brand).toEqual({ name: 'Juniper Cloud', primaryColor: '#ffd400', logo: null })
            expect(posthog.capture).toHaveBeenCalledWith('email brand github detection', { outcome: 'partial' })
        })

        it('keeps crediting a kept logo to the website it came from', async () => {
            starter.actions.resetBrand()
            useMocks(answeringDetection(detectedJuniper))
            await loadDetection()
            useMocks(answeringGitHub(200, { ...githubJuniper, logo_url: null }))

            await expectLogic(starter, () =>
                starter.actions.detectBrandFromGitHub(7, 'juniper/studio')
            ).toDispatchActions(['detectBrandFromGitHubSuccess'])
            await expectLogic(starter, () => starter.actions.submitBrand()).toDispatchActions(['submitBrandSuccess'])

            expect(starter.values.hostedLogoFrom).toBe('website')
            expect(posthog.capture).toHaveBeenCalledWith(
                'email branded starter generated',
                expect.objectContaining({ prefilled_from: 'github', logo_source: 'website' })
            )
        })

        it('does not build the starter while a detection is still running', async () => {
            useMocks({ post: { [GITHUB_DETECTION_URL]: () => new Promise(() => {}) } })
            starter.actions.detectBrandFromGitHub(7, 'juniper/studio')

            await expectLogic(starter, () => starter.actions.submitBrand()).toDispatchActions(['submitBrandFailure'])

            expect(savedBrands).toEqual([])
            expect(lemonToast.error).toHaveBeenCalledWith('Reading your GitHub repository')
        })

        it('shows why detection failed and leaves the form as it was', async () => {
            useMocks(answeringGitHub(429, { detail: 'GitHub is busy or unavailable, try again.' }))

            await expectLogic(starter, () =>
                starter.actions.detectBrandFromGitHub(7, 'juniper/studio')
            ).toDispatchActions(['detectBrandFromGitHubFailure'])

            expect(starter.values.githubDetectionError).toBe('GitHub is busy or unavailable, try again.')
            expect(starter.values.brand).toEqual({ name: 'Juniper Studio', primaryColor: '#ffd400', logo: null })
            expect(starter.values.prefilledFrom).toBeNull()
            expect(posthog.capture).toHaveBeenCalledWith('email brand github detection', { outcome: 'failed' })
        })
    })
})
