import { MOCK_DEFAULT_PROJECT, MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { emailBrandFlowLogic } from './emailBrandFlowLogic'
import { exampleDetection, exampleBrand } from './fixtures'
import type { BrandDraft } from './utils'

const SUGGESTIONS = {
    integration_id: 7,
    repositories: [
        {
            id: 11,
            name: 'juniper-web',
            full_name: 'example/juniper-web',
            language: 'TypeScript',
            pushed_at: null,
            reasons: ['name_match', 'web_language'],
        },
    ],
}

describe('emailBrandFlowLogic', () => {
    let logic: ReturnType<typeof emailBrandFlowLogic.build>
    let capture: jest.SpyInstance
    const onComplete = jest.fn()

    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:id/email_brand/current/': () => [404, { detail: 'Not found.' }],
                '/api/projects/:id/email_brand/suggest_repository/': SUGGESTIONS,
            },
        })
        useMocks({
            post: {
                '/api/projects/:id/email_brand/preview_starter_design/': {
                    name: 'Juniper starter template',
                    description: 'Created from your Email brand.',
                    subject: 'Welcome',
                    design: { body: { rows: [], values: {} } },
                },
            },
        })
        initKeaTests()
        capture = jest.spyOn(posthog, 'capture')
        onComplete.mockClear()
        logic = emailBrandFlowLogic({ entryPoint: 'template_library', onComplete })
    })

    afterEach(() => {
        logic.unmount()
        capture.mockRestore()
    })

    it('detects without saving, then saves the reviewed values', async () => {
        const saved = jest.fn(async ({ request }) => [
            200,
            { ...exampleBrand, ...((await request.json()) as Record<string, unknown>) },
        ])
        useMocks({
            post: { '/api/projects/:id/email_brand/detect/': exampleDetection },
            patch: { '/api/projects/:id/email_brand/current/': saved },
        })
        await expectLogic(logic, () => {
            logic.mount()
        }).toFinishAllListeners()
        await expectLogic(logic, () => logic.actions.detect()).toFinishAllListeners()
        logic.actions.reviewDetection()
        expect(logic.values.draft.name).toBe('Juniper')
        expect(logic.values.draft.primary_color).toBe('#276749')
        expect(saved).not.toHaveBeenCalled()
        logic.actions.editField('name', 'Juniper Mail')
        await expectLogic(logic, () => logic.actions.save(false)).toFinishAllListeners()
        expect(onComplete).toHaveBeenCalledWith({
            emailBrand: expect.objectContaining({ name: 'Juniper Mail' }),
            templateId: null,
        })
        expect(capture).toHaveBeenCalledWith(
            'email brand detected',
            expect.objectContaining({ fields_found: 6, monorepo: false })
        )
        expect(capture).toHaveBeenCalledWith('email brand saved', { edited_fields: ['name'], source: 'detected' })
    })

    it('previews unsaved edits without saving the brand', async () => {
        const save = jest.fn(() => exampleBrand)
        const preview = jest.fn(async ({ request }) => {
            const draft = (await request.json()) as BrandDraft
            return {
                name: `${draft.name} starter template`,
                description: 'Created from your Email brand.',
                subject: 'Welcome',
                design: { body: { rows: [], values: {} } },
            }
        })
        useMocks({
            post: { '/api/projects/:id/email_brand/preview_starter_design/': preview },
            patch: { '/api/projects/:id/email_brand/current/': save },
        })
        await expectLogic(logic, () => {
            logic.mount()
        }).toFinishAllListeners()
        logic.actions.skipToManual()
        await expectLogic(logic, () => logic.actions.editField('name', 'Juniper Mail')).toFinishAllListeners()
        expect(logic.values.preview?.name).toBe('Juniper Mail starter template')
        expect(save).not.toHaveBeenCalled()
    })

    it('preserves manually saved brand values when detecting a repository', async () => {
        useMocks({
            get: {
                '/api/projects/:id/email_brand/current/': {
                    ...exampleBrand,
                    name: 'Juniper Mail',
                    sources: {},
                    source_repository: '',
                },
            },
            post: { '/api/projects/:id/email_brand/detect/': exampleDetection },
        })
        await expectLogic(logic, () => {
            logic.mount()
        }).toFinishAllListeners()
        await expectLogic(logic, () => logic.actions.detect()).toFinishAllListeners()
        expect(logic.values.draft.name).toBe('Juniper Mail')
        expect(logic.values.conflicts.name?.value).toBe('Juniper')
    })

    it('asks before replacing an edited value and refreshes untouched values', async () => {
        useMocks({ post: { '/api/projects/:id/email_brand/detect/': exampleDetection } })
        await expectLogic(logic, () => {
            logic.mount()
        }).toFinishAllListeners()
        await expectLogic(logic, () => logic.actions.detect()).toFinishAllListeners()
        logic.actions.reviewDetection()
        logic.actions.editField('primary_color', '#ff5500')
        useMocks({
            post: {
                '/api/projects/:id/email_brand/detect/': {
                    ...exampleDetection,
                    proposal: {
                        ...exampleDetection.proposal,
                        name: { ...exampleDetection.proposal.name, value: 'Juniper Studio' },
                        primary_color: { ...exampleDetection.proposal.primary_color, value: '#225588' },
                    },
                },
            },
        })
        await expectLogic(logic, () => logic.actions.detect(true)).toFinishAllListeners()
        expect(logic.values.draft.name).toBe('Juniper Studio')
        expect(logic.values.draft.primary_color).toBe('#ff5500')
        expect(logic.values.conflicts.primary_color?.value).toBe('#225588')
        logic.actions.resolveConflict('primary_color', 'detected')
        expect(logic.values.draft.primary_color).toBe('#225588')
        expect(logic.values.conflicts).toEqual({})
        expect(logic.values.editedFields).toEqual([])
    })

    it.each(['skipped', 'nothing found'])('lets a user finish by hand when GitHub is %s', async (scenario) => {
        useMocks({
            get: { '/api/projects/:id/email_brand/suggest_repository/': { integration_id: null, repositories: [] } },
            patch: {
                '/api/projects/:id/email_brand/current/': async ({ request }) => [
                    200,
                    { ...exampleBrand, ...((await request.json()) as Record<string, unknown>) },
                ],
            },
        })
        await expectLogic(logic, () => {
            logic.mount()
        }).toFinishAllListeners()
        expect(logic.values.step).toBe('connect')
        if (scenario === 'nothing found') {
            useMocks({
                get: { '/api/projects/:id/email_brand/suggest_repository/': SUGGESTIONS },
                post: {
                    '/api/projects/:id/email_brand/detect/': {
                        ...exampleDetection,
                        proposal: {
                            name: null,
                            primary_color: null,
                            accent_color: null,
                            text_color: null,
                            background_color: null,
                            font_family: null,
                        },
                    },
                },
            })
            await expectLogic(logic, () => logic.actions.refreshConnection()).toFinishAllListeners()
            await expectLogic(logic, () => logic.actions.detect()).toFinishAllListeners()
            logic.actions.reviewDetection()
            expect(logic.values.nothingFound).toBe(true)
        } else {
            logic.actions.skipToManual()
        }
        expect(logic.values.step).toBe('review')
        logic.actions.editField('name', 'Juniper Mail')
        await expectLogic(logic, () => logic.actions.save(false)).toFinishAllListeners()
        expect(onComplete).toHaveBeenCalledWith({
            emailBrand: expect.objectContaining({ name: 'Juniper Mail' }),
            templateId: null,
        })
    })

    it.each([
        ['github_disconnected', 400, 'connect'],
        ['github_busy', 429, 'repository'],
        ['repository_unreadable', 400, 'repository'],
    ])('offers the right recovery for %s', async (code, status, step) => {
        useMocks({
            post: {
                '/api/projects/:id/email_brand/detect/': () => [
                    status,
                    { code, detail: 'Detection could not finish.' },
                ],
            },
        })
        await expectLogic(logic, () => {
            logic.mount()
        }).toFinishAllListeners()
        await expectLogic(logic, () => logic.actions.detect()).toFinishAllListeners()
        logic.actions.reviewDetection()
        expect(logic.values.step).toBe(step)
        expect(logic.values.error?.code).toBe(code)
        expect(capture).toHaveBeenCalledWith('email brand detection failed', { reason: code })
        expect(logic.values.busy).toBe(false)
    })

    it.each(['server', 'editor'])(
        'creates a starter through the %s path in the current environment',
        async (outcome) => {
            useMocks({
                patch: { '/api/projects/:id/email_brand/current/': exampleBrand },
                post: {
                    '/api/projects/:id/email_brand/create_starter_template/': ({ params }) => {
                        expect(params.id).toBe('42')
                        return outcome === 'server'
                            ? [201, { template_id: 'starter-209' }]
                            : [422, { code: 'design_rendering_unavailable', detail: 'Open the editor.' }]
                    },
                },
            })
            initKeaTests(true, { ...MOCK_DEFAULT_TEAM, id: 42 }, { ...MOCK_DEFAULT_PROJECT, id: 9 })
            logic = emailBrandFlowLogic({ entryPoint: 'template_library', onComplete })
            await expectLogic(logic, () => {
                logic.mount()
            }).toFinishAllListeners()
            logic.actions.skipToManual()
            await expectLogic(logic, () => logic.actions.save(true)).toFinishAllListeners()
            expect(onComplete).toHaveBeenCalledWith({
                emailBrand: exampleBrand,
                templateId: outcome === 'server' ? 'starter-209' : null,
            })
            expect(capture.mock.calls.filter(([event]) => event === 'email brand template created')).toEqual([
                ['email brand template created', { path: outcome }],
            ])
            if (outcome === 'editor') {
                expect(router.values.searchParams.from).toBe('email_brand')
            }
        }
    )

    it('does not create two starters while the first request is pending', async () => {
        let finish: () => void = () => {}
        const waiting = new Promise<void>((resolve) => {
            finish = resolve
        })
        const create = jest.fn(async () => {
            await waiting
            return [201, { template_id: 'starter-209' }]
        })
        useMocks({
            patch: { '/api/projects/:id/email_brand/current/': exampleBrand },
            post: { '/api/projects/:id/email_brand/create_starter_template/': create },
        })
        await expectLogic(logic, () => {
            logic.mount()
        }).toFinishAllListeners()
        logic.actions.skipToManual()
        logic.actions.save(true)
        await expectLogic(logic).toDispatchActions(['createEmailBrandStarterTemplate'])
        expect(logic.values.busy).toBe(true)
        logic.actions.save(true)
        finish()
        await expectLogic(logic).toFinishAllListeners()
        expect(create).toHaveBeenCalledTimes(1)
        expect(onComplete).toHaveBeenCalledTimes(1)
    })

    it('rasterizes an untrusted SVG as an image and uploads a PNG to the email library', async () => {
        const image = {
            naturalWidth: 640,
            naturalHeight: 320,
            onload: null as (() => void) | null,
            onerror: null,
            set src(_value: string) {
                this.onload?.()
            },
        }
        const createUrl = jest.fn(() => 'blob:example-logo')
        const revokeUrl = jest.fn()
        URL.createObjectURL = createUrl
        URL.revokeObjectURL = revokeUrl
        const imageSpy = jest.spyOn(window, 'Image').mockImplementation(() => image as unknown as HTMLImageElement)
        const drawImage = jest.fn()
        const canvasSpy = jest
            .spyOn(HTMLCanvasElement.prototype, 'getContext')
            .mockReturnValue({ drawImage } as unknown as GPUCanvasContext)
        const blobSpy = jest
            .spyOn(HTMLCanvasElement.prototype, 'toBlob')
            .mockImplementation((callback) => callback(new Blob(['invented PNG'], { type: 'image/png' })))
        const upload = jest.fn(async ({ request }) => {
            const data = await request.formData()
            expect(data.get('purpose')).toBe('email')
            expect((data.get('image') as File).type).toBe('image/png')
            return { id: 'logo-209', image_location: 'https://example.com/logo.png' }
        })
        useMocks({
            post: {
                '/api/projects/:id/email_brand/import_logo/': {
                    outcome: 'svg_needs_rasterizing',
                    svg: '<svg xmlns="http://www.w3.org/2000/svg" width="640" height="320"><script>alert(1)</script><rect width="640" height="320" fill="#276749" /></svg>',
                    media_id: null,
                    url: null,
                },
                '/api/projects/:id/uploaded_media/': upload,
            },
        })
        await expectLogic(logic, () => {
            logic.mount()
        }).toFinishAllListeners()
        await expectLogic(logic, () => logic.actions.pickLogo('public/logo.svg')).toFinishAllListeners()
        expect(logic.values.draft.logo).toBe('logo-209')
        expect(logic.values.logoUrl).toBe('https://example.com/logo.png')
        expect(drawImage).toHaveBeenCalledWith(image, 0, 0, 320, 160)
        expect(revokeUrl).toHaveBeenCalledWith('blob:example-logo')
        expect(document.querySelector('svg')).toBeNull()
        imageSpy.mockRestore()
        canvasSpy.mockRestore()
        blobSpy.mockRestore()
    })

    it('asks before replacing a logo the user removed on re-detection', async () => {
        useMocks({
            post: {
                '/api/projects/:id/email_brand/detect/': {
                    ...exampleDetection,
                    logo_candidates: [{ path: 'public/logo.png', width: 320, height: 120 }],
                },
                '/api/projects/:id/email_brand/import_logo/': {
                    outcome: 'imported',
                    media_id: 'logo-209',
                    url: 'https://example.com/logo.png',
                    svg: null,
                },
            },
        })
        await expectLogic(logic, () => {
            logic.mount()
        }).toFinishAllListeners()
        await expectLogic(logic, () => logic.actions.detect()).toFinishAllListeners()
        await expectLogic(logic, () => logic.actions.reviewDetection()).toFinishAllListeners()
        expect(logic.values.draft.logo).toBe('logo-209')
        logic.actions.removeLogo()
        await expectLogic(logic, () => logic.actions.detect(true)).toFinishAllListeners()
        await expectLogic(logic, () => logic.actions.reviewDetection()).toFinishAllListeners()
        expect(logic.values.draft.logo).toBeNull()
        expect(logic.values.logoConflict).toEqual({ path: 'public/logo.png' })
        await expectLogic(logic, () => logic.actions.resolveLogoConflict('detected')).toFinishAllListeners()
        expect(logic.values.draft.logo).toBe('logo-209')
        expect(logic.values.logoConflict).toBeNull()
    })

    it('asks which app to read in a monorepo before review', async () => {
        const detect = jest.fn(async ({ request }) => {
            const data = await request.json()
            return { ...exampleDetection, app_root: data.app_root ?? 'apps/web', app_root_alternatives: ['apps/admin'] }
        })
        useMocks({ post: { '/api/projects/:id/email_brand/detect/': detect } })
        await expectLogic(logic, () => {
            logic.mount()
        }).toFinishAllListeners()
        await expectLogic(logic, () => logic.actions.detect()).toFinishAllListeners()
        expect(logic.values.step).toBe('app')
        await expectLogic(logic, () => logic.actions.chooseApp('apps/admin')).toFinishAllListeners()
        expect(logic.values.draft.app_root).toBe('apps/admin')
        expect(logic.values.step).toBe('files')
        logic.actions.reviewDetection()
        expect(logic.values.step).toBe('review')
    })

    it('preselects the suggested repository and reports opening once', async () => {
        await expectLogic(logic, () => {
            logic.mount()
        }).toFinishAllListeners()
        expect(logic.values.repository).toBe('example/juniper-web')
        expect(logic.values.integrationId).toBe(7)
        expect(logic.values.step).toBe('repository')
        expect(capture.mock.calls.filter(([event]) => event === 'email brand flow opened')).toEqual([
            ['email brand flow opened', { entry_point: 'template_library' }],
        ])
    })
    it('redetects the saved source rather than a new suggestion', async () => {
        const detect = jest.fn(async ({ request }) => {
            expect(await request.json()).toEqual(
                expect.objectContaining({ repository: 'example/saved-app', app_root: 'apps/web' })
            )
            return exampleDetection
        })
        useMocks({
            get: {
                '/api/projects/:id/email_brand/current/': {
                    ...exampleBrand,
                    source_repository: 'example/saved-app',
                    app_root: 'apps/web',
                },
            },
            post: { '/api/projects/:id/email_brand/detect/': detect },
        })
        await expectLogic(logic, () => {
            logic.mount()
        }).toFinishAllListeners()
        await expectLogic(logic, () => logic.actions.detect(true)).toFinishAllListeners()
        expect(detect).toHaveBeenCalledTimes(1)
        expect(logic.values.error).toBeNull()
    })

    it('preserves a kept saved edit when its detection signal disappears and returns', async () => {
        useMocks({
            get: { '/api/projects/:id/email_brand/current/': { ...exampleBrand, primary_color: '#ff5500' } },
            post: {
                '/api/projects/:id/email_brand/detect/': {
                    ...exampleDetection,
                    proposal: { ...exampleDetection.proposal, primary_color: null },
                },
            },
        })
        await expectLogic(logic, () => {
            logic.mount()
        }).toFinishAllListeners()
        await expectLogic(logic, () => logic.actions.detect(true)).toFinishAllListeners()
        logic.actions.resolveConflict('primary_color', 'mine')
        useMocks({ post: { '/api/projects/:id/email_brand/detect/': exampleDetection } })
        await expectLogic(logic, () => logic.actions.detect(true)).toFinishAllListeners()
        expect(logic.values.draft.primary_color).toBe('#ff5500')
        expect(logic.values.conflicts.primary_color).toEqual({ value: '#276749' })
    })

    it('keeps manual review when a pending connection check finishes', async () => {
        let finish: () => void = () => {}
        const waiting = new Promise<void>((resolve) => {
            finish = resolve
        })
        const connection = jest.fn(async () => {
            await waiting
            return SUGGESTIONS
        })
        await expectLogic(logic, () => {
            logic.mount()
        }).toFinishAllListeners()
        useMocks({ get: { '/api/projects/:id/email_brand/suggest_repository/': connection } })
        logic.actions.refreshConnection()
        await expectLogic(logic).toDispatchActions(['loadEmailBrandConnection'])
        logic.actions.skipToManual()
        logic.actions.editField('name', 'Juniper Mail')
        finish()
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.step).toBe('review')
        expect(logic.values.draft.name).toBe('Juniper Mail')
    })

    it.each(['save', 'starter'])('ignores a pending %s response after cancel and reopen', async (phase) => {
        let finish: () => void = () => {}
        const waiting = new Promise<void>((resolve) => {
            finish = resolve
        })
        const create = jest.fn(async () => {
            if (phase === 'starter') {
                await waiting
            }
            return [201, { template_id: 'old-starter' }]
        })
        useMocks({
            patch: {
                '/api/projects/:id/email_brand/current/': async () => {
                    if (phase === 'save') {
                        await waiting
                    }
                    return exampleBrand
                },
            },
            post: { '/api/projects/:id/email_brand/create_starter_template/': create },
        })
        await expectLogic(logic, () => {
            logic.mount()
        }).toFinishAllListeners()
        logic.actions.skipToManual()
        logic.actions.save(true)
        await expectLogic(logic).toDispatchActions([
            phase === 'save' ? 'saveEmailBrand' : 'createEmailBrandStarterTemplate',
        ])
        logic.unmount()
        const reopened = jest.fn()
        logic = emailBrandFlowLogic({ entryPoint: 'template_library', onComplete: reopened })
        await expectLogic(logic, () => {
            logic.mount()
        }).toDispatchActions(['loadEmailBrandInitialSuccess'])
        logic.actions.skipToManual()
        logic.actions.editField('name', 'New draft')
        finish()
        await new Promise((resolve) => setTimeout(resolve, 150))
        await expectLogic(logic).toFinishAllListeners()
        expect(reopened).not.toHaveBeenCalled()
        expect(onComplete).not.toHaveBeenCalled()
        expect(logic.values.completed).toBe(false)
        expect(logic.values.draft.name).toBe('New draft')
        expect(create).toHaveBeenCalledTimes(phase === 'save' ? 0 : 1)
    })

    it('does not retry starter creation after an uncertain response', async () => {
        const create = jest.fn(() => [500, { detail: 'Response unavailable' }])
        useMocks({
            patch: { '/api/projects/:id/email_brand/current/': exampleBrand },
            post: { '/api/projects/:id/email_brand/create_starter_template/': create },
        })
        await expectLogic(logic, () => {
            logic.mount()
        }).toFinishAllListeners()
        logic.actions.skipToManual()
        await expectLogic(logic, () => logic.actions.save(true)).toFinishAllListeners()
        await expectLogic(logic, () => logic.actions.save(true)).toFinishAllListeners()
        expect(create).toHaveBeenCalledTimes(1)
        expect(logic.values.error?.code).toBe('create_outcome_unknown')
        await expectLogic(logic, () => logic.actions.save(false)).toFinishAllListeners()
        expect(onComplete).toHaveBeenCalledWith({ emailBrand: exampleBrand, templateId: null })
    })

    it('retains a loaded brand when repository suggestions fail', async () => {
        useMocks({
            get: {
                '/api/projects/:id/email_brand/current/': exampleBrand,
                '/api/projects/:id/email_brand/suggest_repository/': () => [
                    429,
                    { code: 'github_busy', detail: 'GitHub is busy' },
                ],
            },
        })
        await expectLogic(logic, () => {
            logic.mount()
        }).toFinishAllListeners()
        expect(logic.values.step).toBe('review')
        expect(logic.values.draft.name).toBe(exampleBrand.name)
        expect(logic.values.draft.primary_color).toBe(exampleBrand.primary_color)
    })

    it('cannot save defaults when the saved-brand lookup fails', async () => {
        const save = jest.fn(() => exampleBrand)
        useMocks({
            get: { '/api/projects/:id/email_brand/current/': () => [500, { detail: 'Unavailable' }] },
            patch: { '/api/projects/:id/email_brand/current/': save },
        })
        await expectLogic(logic, () => {
            logic.mount()
        }).toFinishAllListeners()
        logic.actions.skipToManual()
        await expectLogic(logic, () => logic.actions.save(false)).toFinishAllListeners()
        expect(save).not.toHaveBeenCalled()
        expect(logic.values.step).toBe('loading')
    })
    it('releases edit ownership when the user accepts a missing detection value', async () => {
        useMocks({ post: { '/api/projects/:id/email_brand/detect/': exampleDetection } })
        await expectLogic(logic, () => {
            logic.mount()
        }).toFinishAllListeners()
        await expectLogic(logic, () => logic.actions.detect()).toFinishAllListeners()
        logic.actions.editField('primary_color', '#ff5500')
        useMocks({
            post: {
                '/api/projects/:id/email_brand/detect/': {
                    ...exampleDetection,
                    proposal: { ...exampleDetection.proposal, primary_color: null },
                },
            },
        })
        await expectLogic(logic, () => logic.actions.detect(true)).toFinishAllListeners()
        logic.actions.resolveAllConflicts('detected')
        expect(logic.values.editedFields).not.toContain('primary_color')
        useMocks({ post: { '/api/projects/:id/email_brand/detect/': exampleDetection } })
        await expectLogic(logic, () => logic.actions.detect(true)).toFinishAllListeners()
        expect(logic.values.draft.primary_color).toBe('#276749')
        expect(logic.values.conflicts).toEqual({})
    })

    it('lets onboarding handle completion without navigating to the library editor', async () => {
        const navigate = jest.spyOn(router.actions, 'push')
        logic = emailBrandFlowLogic({ entryPoint: 'onboarding', onComplete })
        useMocks({
            patch: { '/api/projects/:id/email_brand/current/': exampleBrand },
            post: {
                '/api/projects/:id/email_brand/create_starter_template/': () => [
                    422,
                    { code: 'design_rendering_unavailable', detail: 'Editor required' },
                ],
            },
        })
        await expectLogic(logic, () => {
            logic.mount()
        }).toFinishAllListeners()
        logic.actions.skipToManual()
        await expectLogic(logic, () => logic.actions.save(true)).toFinishAllListeners()
        expect(navigate).not.toHaveBeenCalled()
        expect(onComplete).toHaveBeenCalledWith({ emailBrand: exampleBrand, templateId: null })
        navigate.mockRestore()
    })

    it('keeps detection running when the user switches tabs', async () => {
        let finish: () => void = () => {}
        const waiting = new Promise<void>((resolve) => {
            finish = resolve
        })
        useMocks({
            post: {
                '/api/projects/:id/email_brand/detect/': async () => {
                    await waiting
                    return exampleDetection
                },
            },
        })
        await expectLogic(logic, () => {
            logic.mount()
        }).toFinishAllListeners()
        logic.actions.detect()
        await expectLogic(logic).toDispatchActions(['loadEmailBrandDetection'])
        Object.defineProperty(document, 'hidden', { configurable: true, value: true })
        document.dispatchEvent(new Event('visibilitychange'))
        Object.defineProperty(document, 'hidden', { configurable: true, value: false })
        document.dispatchEvent(new Event('visibilitychange'))
        finish()
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.step).toBe('files')
        expect(logic.values.error).toBeNull()
    })

    it('waits for an upload before accepting a detected logo conflict', async () => {
        let finish: () => void = () => {}
        const waiting = new Promise<void>((resolve) => {
            finish = resolve
        })
        useMocks({
            post: {
                '/api/projects/:id/uploaded_media/': async () => {
                    await waiting
                    return { id: 'new-logo', image_location: 'https://example.com/logo.png' }
                },
            },
        })
        await expectLogic(logic, () => {
            logic.mount()
        }).toFinishAllListeners()
        logic.actions.setLogoConflict({ path: null })
        logic.actions.uploadLogo(new File(['invented PNG'], 'logo.png', { type: 'image/png' }))
        await expectLogic(logic).toDispatchActions(['loadEmailBrandLogo'])
        logic.actions.resolveAllConflicts('detected')
        expect(logic.values.logoConflict).toEqual({ path: null })
        finish()
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.resolveLogoConflict('detected')
        expect(logic.values.draft.logo).toBeNull()
        expect(logic.values.logoConflict).toBeNull()
    })

    it('clears a repository selection without storing null', async () => {
        await expectLogic(logic, () => {
            logic.mount()
        }).toFinishAllListeners()
        logic.actions.setRepository(null as unknown as string)
        expect(logic.values.repository).toBe('')
    })

    it('reports connected and picked funnel steps once with their properties', async () => {
        useMocks({ post: { '/api/projects/:id/email_brand/detect/': exampleDetection } })
        await expectLogic(logic, () => {
            logic.mount()
        }).toFinishAllListeners()
        await expectLogic(logic, () => logic.actions.refreshConnection()).toFinishAllListeners()
        await expectLogic(logic, () => logic.actions.refreshConnection()).toFinishAllListeners()
        await expectLogic(logic, () => logic.actions.detect()).toFinishAllListeners()
        await expectLogic(logic, () => logic.actions.detect(true)).toFinishAllListeners()
        expect(capture.mock.calls.filter(([event]) => event === 'email brand github connected')).toEqual([
            ['email brand github connected'],
        ])
        expect(capture.mock.calls.filter(([event]) => event === 'email brand repository picked')).toEqual([
            ['email brand repository picked', { suggested: true, rank: 1 }],
        ])
    })
    it('offers reconnection when GitHub disconnects during logo import', async () => {
        useMocks({
            post: {
                '/api/projects/:id/email_brand/import_logo/': () => [
                    400,
                    { code: 'github_disconnected', detail: 'Reconnect GitHub' },
                ],
            },
        })
        await expectLogic(logic, () => {
            logic.mount()
        }).toFinishAllListeners()
        logic.actions.skipToManual()
        logic.actions.editField('name', 'Juniper Mail')
        await expectLogic(logic, () => logic.actions.pickLogo('public/logo.png')).toFinishAllListeners()
        expect(logic.values.step).toBe('connect')
        expect(logic.values.draft.name).toBe('Juniper Mail')
        expect(logic.values.error?.code).toBe('github_disconnected')
    })
    it('keeps an explicitly chosen repository logo protected after saving and reopening', async () => {
        let savedBrand = exampleBrand
        const importLogo = jest.fn(async ({ request }) => {
            const body = await request.json()
            return {
                outcome: 'imported',
                media_id: body.path === 'public/default.png' ? 'default-logo' : 'chosen-logo',
                url: 'https://example.com/logo.png',
                svg: null,
            }
        })
        useMocks({
            post: {
                '/api/projects/:id/email_brand/detect/': {
                    ...exampleDetection,
                    logo_candidates: [
                        { path: 'public/default.png', width: 320, height: 120 },
                        { path: 'public/chosen.png', width: 320, height: 120 },
                    ],
                },
                '/api/projects/:id/email_brand/import_logo/': importLogo,
            },
            patch: {
                '/api/projects/:id/email_brand/current/': async ({ request }) => {
                    const draft = (await request.json()) as BrandDraft
                    savedBrand = {
                        ...exampleBrand,
                        ...draft,
                        edited: { ...exampleBrand.edited, logo: draft.logo !== draft.sources.logo?.detected_value },
                    }
                    return savedBrand
                },
            },
        })
        await expectLogic(logic, () => {
            logic.mount()
        }).toFinishAllListeners()
        await expectLogic(logic, () => logic.actions.detect()).toFinishAllListeners()
        await expectLogic(logic, () => logic.actions.reviewDetection()).toFinishAllListeners()
        await expectLogic(logic, () => logic.actions.pickLogo('public/chosen.png')).toFinishAllListeners()
        await expectLogic(logic, () => logic.actions.save(false)).toFinishAllListeners()
        logic.unmount()
        useMocks({ get: { '/api/projects/:id/email_brand/current/': () => savedBrand } })
        logic = emailBrandFlowLogic({ entryPoint: 'template_library', onComplete })
        await expectLogic(logic, () => {
            logic.mount()
        }).toFinishAllListeners()
        await expectLogic(logic, () => logic.actions.detect(true)).toFinishAllListeners()
        await expectLogic(logic, () => logic.actions.reviewDetection()).toFinishAllListeners()
        expect(logic.values.draft.logo).toBe('chosen-logo')
        expect(logic.values.logoConflict).toEqual({ path: 'public/default.png' })
        expect(importLogo).toHaveBeenCalledTimes(2)
    })
    it('preserves an edited default through signal loss and save/reopen', async () => {
        let savedBrand = exampleBrand
        useMocks({
            get: { '/api/projects/:id/email_brand/current/': exampleBrand },
            post: {
                '/api/projects/:id/email_brand/detect/': {
                    ...exampleDetection,
                    proposal: { ...exampleDetection.proposal, primary_color: null },
                },
            },
            patch: {
                '/api/projects/:id/email_brand/current/': async ({ request }) => {
                    savedBrand = { ...exampleBrand, ...((await request.json()) as BrandDraft) }
                    return savedBrand
                },
            },
        })
        await expectLogic(logic, () => {
            logic.mount()
        }).toFinishAllListeners()
        logic.actions.editField('primary_color', '#111111')
        await expectLogic(logic, () => logic.actions.detect(true)).toFinishAllListeners()
        await expectLogic(logic, () => logic.actions.save(false)).toFinishAllListeners()
        logic.unmount()
        useMocks({
            get: { '/api/projects/:id/email_brand/current/': () => savedBrand },
            post: { '/api/projects/:id/email_brand/detect/': exampleDetection },
        })
        logic = emailBrandFlowLogic({ entryPoint: 'template_library', onComplete })
        await expectLogic(logic, () => {
            logic.mount()
        }).toFinishAllListeners()
        await expectLogic(logic, () => logic.actions.detect(true)).toFinishAllListeners()
        expect(logic.values.draft.primary_color).toBe('#111111')
        expect(logic.values.conflicts.primary_color).toEqual({ value: '#276749' })
    })

    it('clears obsolete logo provenance when adopting detection without a logo', async () => {
        useMocks({
            get: {
                '/api/projects/:id/email_brand/current/': {
                    ...exampleBrand,
                    logo: 'old-logo',
                    sources: {
                        ...exampleBrand.sources,
                        logo: { path: 'public/old.png', line: null, detected_value: 'old-logo' },
                    },
                },
            },
            post: { '/api/projects/:id/email_brand/detect/': exampleDetection },
        })
        await expectLogic(logic, () => {
            logic.mount()
        }).toFinishAllListeners()
        await expectLogic(logic, () => logic.actions.detect(true)).toFinishAllListeners()
        await expectLogic(logic, () => logic.actions.reviewDetection()).toFinishAllListeners()
        expect(logic.values.draft.logo).toBeNull()
        expect(logic.values.draft.sources.logo).toBeUndefined()
        expect(logic.values.logoEdited).toBe(false)
    })
})
