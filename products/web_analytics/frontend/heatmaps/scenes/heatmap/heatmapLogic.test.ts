import { MOCK_DEFAULT_USER } from 'lib/api.mock'

import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'
import { heatmapDataLogic } from 'lib/components/heatmaps/heatmapDataLogic'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import { initKeaTests } from '~/test/init'
import { AccessControlLevel, HeatmapSource, HeatmapType } from '~/types'

import * as heatmapApi from 'products/web_analytics/frontend/generated/api'
import type { HeatmapScreenshotResponseApi } from 'products/web_analytics/frontend/generated/api.schemas'

import { heatmapsSceneLogic } from '../heatmaps/heatmapsSceneLogic'
import { computeLockedWidth, heatmapLogic, resolveHeatmapExportUrl } from './heatmapLogic'

function createDeferred<T>(): { promise: Promise<T>; resolve: (value: T) => void } {
    let resolve!: (value: T) => void
    const promise = new Promise<T>((r) => {
        resolve = r
    })
    return { promise, resolve }
}

describe('heatmapLogic', () => {
    describe('computeLockedWidth', () => {
        it.each([
            ['toolbar', [1440], 1440],
            ['toolbar', [320, 768, 1440], null],
            ['toolbar', [], null],
            ['server', [1024], null],
        ] as const)('computeLockedWidth(%s, %j) → %s', (source, capturedWidths, expected) => {
            expect(computeLockedWidth(source as HeatmapSource, [...capturedWidths])).toBe(expected)
        })
    })

    describe('resolveHeatmapExportUrl', () => {
        const origin = 'https://us.posthog.com'

        it.each([
            [
                'screenshot',
                '/api/environments/1/heatmap_screenshots/42/content/?width=1400',
                'https://example.com/page',
                `${origin}/api/environments/1/heatmap_screenshots/42/content/?width=1400`,
            ],
            [
                'iframe',
                '/api/environments/1/heatmap_screenshots/42/content/',
                'https://example.com/page',
                'https://example.com/page',
            ],
            ['screenshot', null, 'https://example.com/page', ''],
            ['iframe', '/api/something', null, ''],
            [
                'screenshot',
                'https://another.posthog.com/api/environments/1/heatmap_screenshots/42/content/',
                null,
                'https://another.posthog.com/api/environments/1/heatmap_screenshots/42/content/',
            ],
        ] as const)(
            'resolveHeatmapExportUrl(%s, screenshotUrl=%s, displayUrl=%s) → %s',
            (type, screenshotUrl, displayUrl, expected) => {
                expect(resolveHeatmapExportUrl(type as HeatmapType, screenshotUrl, displayUrl, origin)).toBe(expected)
            }
        )
    })

    describe('saving', () => {
        const saved: HeatmapScreenshotResponseApi = {
            id: 'heatmap-1',
            short_id: 'hm_test',
            name: 'Pricing page',
            url: 'https://example.com/pricing',
            data_url: null,
            type: 'screenshot',
            source: 'server',
            status: 'completed',
            has_content: true,
            target_widths: [1440],
            snapshots: [],
            block_consent_modals: false,
            created_by: {
                id: MOCK_DEFAULT_USER.id,
                uuid: MOCK_DEFAULT_USER.uuid,
                email: 'test@example.com',
                hedgehog_config: null,
            },
            created_at: '2024-01-01T00:00:00Z',
            updated_at: '2024-01-01T00:00:00Z',
            exception: null,
            user_access_level: 'editor',
        }
        let logic: ReturnType<typeof heatmapLogic>
        let stored: HeatmapScreenshotResponseApi

        beforeEach(async () => {
            initKeaTests()
            window.POSTHOG_APP_CONTEXT!.resource_access_control = {
                ...window.POSTHOG_APP_CONTEXT!.resource_access_control!,
                heatmap: AccessControlLevel.Editor,
            }
            stored = { ...saved }
            jest.spyOn(api, 'queryHogQL').mockResolvedValue({ results: [] } as any)
            jest.spyOn(api.savedHeatmaps, 'list').mockImplementation(
                async () => ({ results: [stored], count: 1 }) as any
            )
            jest.spyOn(heatmapApi, 'savedRetrieve').mockImplementation(async () => stored)
            jest.spyOn(heatmapApi, 'savedPartialUpdate').mockImplementation(async (_team, _id, data) => {
                stored = { ...stored, ...data }
                return stored
            })
            jest.spyOn(heatmapApi, 'savedRegenerateCreate').mockResolvedValue(saved)
            jest.spyOn(lemonToast, 'success').mockImplementation(() => '')
            jest.spyOn(lemonToast, 'error').mockImplementation(() => '')
            router.actions.push('/heatmaps/hm_test')
            logic = heatmapLogic({ id: 'hm_test' })
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()
        })

        afterEach(() => jest.restoreAllMocks())

        it.each([
            ['name', () => logic.actions.setName('Checkout page')],
            ['page URL', () => logic.actions.setPageUrlDraft('https://example.com/checkout')],
            ['data URL', () => logic.actions.setDataUrl('https://example.com/*')],
            ['capture method', () => logic.actions.setType('iframe')],
            ['consent banners', () => logic.actions.setBlockConsentModals(true)],
        ])('tracks and discards %s edits without saving automatically', async (_label, edit) => {
            expect(logic.values.hasUnsavedChanges).toBe(false)
            edit()
            expect(logic.values.hasUnsavedChanges).toBe(true)
            expect(heatmapApi.savedPartialUpdate).not.toHaveBeenCalled()
            logic.actions.discardChanges()
            expect(logic.values.hasUnsavedChanges).toBe(false)
            expect(logic.values.pageUrlDraft).toBe(saved.url)
        })

        it('ignores reverted edits and viewing preferences', () => {
            logic.actions.setName('Another name')
            logic.actions.setName(saved.name!)
            heatmapDataLogic({ context: 'in-app' }).actions.setCommonFilters({ date_from: '-30d' })
            expect(logic.values.hasUnsavedChanges).toBe(false)
            logic.actions.updateHeatmap()
            expect(heatmapApi.savedPartialUpdate).not.toHaveBeenCalled()
        })

        it('warns when leaving with edits but allows in-page URL updates', () => {
            const initialPath = router.values.location.pathname
            const confirm = jest.spyOn(window, 'confirm').mockReturnValue(false)
            logic.actions.setDataUrl('https://example.com/*')
            heatmapDataLogic({ context: 'in-app' }).actions.setCommonFilters({ date_from: '-30d' })
            expect(confirm).not.toHaveBeenCalled()
            router.actions.push('/heatmaps')
            expect(confirm).toHaveBeenCalledTimes(1)
            expect(router.values.location.pathname).toBe(initialPath)
            expect(logic.values.hasUnsavedChanges).toBe(true)
            confirm.mockReturnValue(true)
            router.actions.push('/heatmaps')
            expect(router.values.location.pathname).toBe(initialPath.replace('/hm_test', ''))
            expect(logic.values.hasUnsavedChanges).toBe(false)
        })

        it.each([true, false])('saves a rename without regenerating a screenshot (ready: %s)', async (ready) => {
            if (!ready) {
                logic.actions.setScreenshotUrl(null)
                logic.actions.setScreenshotError('Screenshot generation failed')
            }
            const screenshotUrl = logic.values.screenshotUrl
            logic.actions.setName('Checkout page')
            await expectLogic(logic, () => logic.actions.updateHeatmap()).toFinishAllListeners()
            await expectLogic(heatmapsSceneLogic).toFinishAllListeners()
            expect(logic.values.hasUnsavedChanges).toBe(false)
            expect(logic.values.loading).toBe(false)
            expect(logic.values.screenshotUrl).toBe(screenshotUrl)
            expect(heatmapApi.savedRegenerateCreate).not.toHaveBeenCalled()
            expect(lemonToast.success).toHaveBeenCalledWith('Heatmap saved')
            expect(heatmapsSceneLogic.values.savedHeatmaps[0].name).toBe('Checkout page')
            await expectLogic(logic, () => logic.actions.load()).toFinishAllListeners()
            expect(logic.values.name).toBe('Checkout page')
        })

        it('saves the visible URL on Enter and waits for the server-generated screenshot', async () => {
            logic.actions.setPageUrlDraft('https://example.com/checkout')
            expect(logic.values.displayUrl).toBe(saved.url)
            await expectLogic(logic, () => logic.actions.updateHeatmap()).toDispatchActions([
                'setSaving',
                'setSavedSettings',
                'pollScreenshotStatus',
            ])
            expect(heatmapApi.savedPartialUpdate).toHaveBeenCalledWith(
                expect.any(String),
                'hm_test',
                expect.objectContaining({ url: 'https://example.com/checkout' })
            )
            expect(logic.values.displayUrl).toBe('https://example.com/checkout')
            expect(logic.values.hasUnsavedChanges).toBe(false)
            expect(heatmapApi.savedRegenerateCreate).not.toHaveBeenCalled()
        })

        it('keeps failed edits for retry', async () => {
            jest.mocked(heatmapApi.savedPartialUpdate).mockRejectedValueOnce(new Error('offline'))
            logic.actions.setName('Checkout page')
            logic.actions.setPageUrlDraft('https://example.com/checkout')
            await expectLogic(logic, () => logic.actions.updateHeatmap()).toFinishAllListeners()
            expect(logic.values.pageUrlDraft).toBe('https://example.com/checkout')
            expect(logic.values.name).toBe('Checkout page')
            expect(logic.values.displayUrl).toBe(saved.url)
            expect(logic.values.hasUnsavedChanges).toBe(true)
            expect(logic.values.saving).toBe(false)
            expect(lemonToast.success).not.toHaveBeenCalled()
            expect(lemonToast.error).toHaveBeenCalled()
        })

        it('regenerates only saved render settings and prevents duplicate generation requests', async () => {
            logic.actions.setBlockConsentModals(true)
            logic.actions.regenerateScreenshot()
            expect(heatmapApi.savedRegenerateCreate).not.toHaveBeenCalled()
            logic.actions.discardChanges()
            const regenerate = createDeferred<HeatmapScreenshotResponseApi>()
            jest.mocked(heatmapApi.savedRegenerateCreate).mockReturnValueOnce(regenerate.promise)
            logic.actions.regenerateScreenshot()
            expect(logic.values.generatingScreenshot).toBe(true)
            logic.actions.regenerateScreenshot()
            expect(heatmapApi.savedRegenerateCreate).toHaveBeenCalledTimes(1)
            regenerate.resolve(saved)
            await expectLogic(logic).toFinishAllListeners()
            expect(logic.values.generatingScreenshot).toBe(false)
            expect(logic.values.screenshotUrl).toBeTruthy()
            expect(logic.values.hasUnsavedChanges).toBe(false)
        })

        it('switches to a fresh screenshot immediately without saving other drafts or submitting twice', async () => {
            stored = { ...saved, type: 'iframe' }
            await expectLogic(logic, () => logic.actions.load()).toFinishAllListeners()
            logic.actions.setName('Unsaved name')
            logic.actions.setPageUrlDraft('https://example.com/unsaved')
            logic.actions.setScreenshotUrl('/old-screenshot.png')
            const save = createDeferred<HeatmapScreenshotResponseApi>()
            jest.mocked(heatmapApi.savedPartialUpdate).mockReturnValueOnce(save.promise)
            logic.actions.switchToScreenshot()
            logic.actions.switchToScreenshot()
            expect(logic.values.saving).toBe(true)
            expect(heatmapApi.savedPartialUpdate).toHaveBeenCalledTimes(1)
            expect(heatmapApi.savedPartialUpdate).toHaveBeenCalledWith(expect.any(String), 'hm_test', {
                type: 'screenshot',
            })
            stored = { ...stored, type: 'screenshot' }
            save.resolve(stored)
            await expectLogic(logic).toFinishAllListeners()
            expect(heatmapApi.savedRegenerateCreate).toHaveBeenCalledTimes(1)
            expect(logic.values.previewType).toBe('screenshot')
            expect(logic.values.name).toBe('Unsaved name')
            expect(logic.values.pageUrlDraft).toBe('https://example.com/unsaved')
            expect(logic.values.hasUnsavedChanges).toBe(true)
            expect(logic.values.saving).toBe(false)
        })

        it('keeps the live preview after a failed switch and allows retry', async () => {
            stored = { ...saved, type: 'iframe' }
            await expectLogic(logic, () => logic.actions.load()).toFinishAllListeners()
            jest.mocked(heatmapApi.savedPartialUpdate).mockRejectedValueOnce(new Error('offline'))
            await expectLogic(logic, () => logic.actions.switchToScreenshot()).toFinishAllListeners()
            expect(logic.values.previewType).toBe('iframe')
            expect(logic.values.type).toBe('iframe')
            expect(logic.values.saving).toBe(false)
            expect(heatmapApi.savedRegenerateCreate).not.toHaveBeenCalled()
            expect(lemonToast.error).toHaveBeenCalled()
            await expectLogic(logic, () => logic.actions.switchToScreenshot()).toFinishAllListeners()
            expect(logic.values.previewType).toBe('screenshot')
            expect(heatmapApi.savedRegenerateCreate).toHaveBeenCalledTimes(1)
        })

        it('prevents duplicate saves and preserves edits made during a request', async () => {
            const save = createDeferred<HeatmapScreenshotResponseApi>()
            jest.mocked(heatmapApi.savedPartialUpdate).mockReturnValueOnce(save.promise)
            logic.actions.setName('Submitted name')
            logic.actions.updateHeatmap()
            expect(logic.values.saving).toBe(true)
            expect(logic.values.loading).toBe(false)
            logic.actions.updateHeatmap()
            expect(heatmapApi.savedPartialUpdate).toHaveBeenCalledTimes(1)
            logic.actions.setName('Later name')
            logic.actions.setPageUrlDraft('https://example.com/later')
            save.resolve({ ...saved, name: 'Submitted name' })
            await expectLogic(logic).toFinishAllListeners()
            expect(logic.values.name).toBe('Later name')
            expect(logic.values.pageUrlDraft).toBe('https://example.com/later')
            expect(logic.values.hasUnsavedChanges).toBe(true)
            logic.actions.discardChanges()
            expect(logic.values.name).toBe('Submitted name')
            expect(logic.values.hasUnsavedChanges).toBe(false)
        })

        it.each(['', 'not-a-url', 'https://example.com/*'])('does not save an invalid page URL: %s', (url) => {
            logic.actions.setPageUrlDraft(url)
            expect(logic.values.saveDisabledReason).toBeTruthy()
            logic.actions.updateHeatmap()
            expect(heatmapApi.savedPartialUpdate).not.toHaveBeenCalled()
        })

        it.each(['viewer', 'toolbar'] as const)('disables unsupported edits for %s', (restriction) => {
            if (restriction === 'viewer') {
                logic.actions.setUserAccessLevel(AccessControlLevel.Viewer)
                expect(logic.values.editDisabledReason).toBeTruthy()
            } else {
                logic.actions.setSource('toolbar')
                expect(logic.values.editDisabledReason).toBeNull()
            }
            expect(logic.values.urlEditDisabledReason).toBeTruthy()
            expect(logic.values.regenerateDisabledReason).toBeTruthy()
        })
    })
})
