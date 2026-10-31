import { MOCK_DEFAULT_USER } from 'lib/api.mock'

import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'
import { ApiError } from 'lib/api-error'
import { heatmapDataLogic } from 'lib/components/heatmaps/heatmapDataLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { dayjs } from 'lib/dayjs'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { initKeaTests } from '~/test/init'
import { AccessControlLevel } from '~/types'

import * as heatmapApi from 'products/web_analytics/frontend/generated/api'
import type {
    HeatmapScreenshotHistoryItemApi,
    HeatmapScreenshotHistoryResponseApi,
    HeatmapScreenshotResponseApi,
} from 'products/web_analytics/frontend/generated/api.schemas'

import { heatmapLogic } from '../scenes/heatmap/heatmapLogic'
import { pageHistoryCaptureLogic } from './pageHistoryCaptureLogic'
import { pageHistoryLogic, selectCapturesBetween } from './pageHistoryLogic'

const saved: HeatmapScreenshotResponseApi = {
    id: 'heatmap-1',
    short_id: 'hm_test',
    name: 'Home page',
    url: 'https://example.com',
    data_url: null,
    type: 'screenshot',
    source: 'server',
    status: 'completed',
    has_content: true,
    target_widths: [1024],
    snapshots: [{ width: 1024, has_content: true }],
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

const capture = (
    id: string,
    capturedOn: string,
    overrides: Partial<HeatmapScreenshotHistoryItemApi> = {}
): HeatmapScreenshotHistoryItemApi => ({
    id,
    captured_on: capturedOn,
    captured_at: `${capturedOn}T02:40:00Z`,
    width: 1024,
    timezone: 'UTC',
    day_start: `${capturedOn}T00:00:00Z`,
    day_end: dayjs.utc(capturedOn).add(1, 'day').format('YYYY-MM-DD[T]HH:mm:ss[Z]'),
    expires_at: dayjs().add(30, 'day').toISOString(),
    revision: id,
    latest_request: null,
    thumbnail_url: null,
    trigger: 'scheduled',
    status: 'ok',
    failure_cause: null,
    page_status: 200,
    content_url: `/api/projects/997/saved/hm_test/screenshot_history/${id}/content/`,
    ...overrides,
})

const historyResponse = (results: HeatmapScreenshotHistoryItemApi[]): HeatmapScreenshotHistoryResponseApi => ({
    width: 1024,
    retention_days: 90,
    storage_available: true,
    results,
})

const captures = [
    capture('cap-3', '2024-05-03'),
    capture('cap-2', '2024-05-02', {
        status: 'failed',
        failure_cause: 'browserless_timeout',
        content_url: null,
        revision: null,
    }),
    capture('cap-1', '2024-05-01'),
]

describe('pageHistoryLogic', () => {
    describe('selectCapturesBetween', () => {
        it.each([
            ['a single day', 'cap-1', 'cap-1', ['cap-1']],
            ['a range in either direction', 'cap-3', 'cap-1', ['cap-1', 'cap-3']],
            ['a failed day on its own', 'cap-2', 'cap-2', []],
            ['no anchor', null, null, []],
            ['an expired endpoint', 'cap-1', 'expired', []],
            ['a failed endpoint', 'cap-1', 'cap-2', []],
        ])('selects %s', (_label, anchorId, extentId, expected) => {
            expect(selectCapturesBetween(captures, anchorId, extentId).map((c) => c.id)).toEqual(expected)
        })

        it.each([{ width: 1440 }, { timezone: 'America/New_York' }])('rejects incompatible ranges %s', (difference) => {
            const mixed = [capture('a', '2024-05-01'), capture('b', '2024-05-02', difference)]
            expect(selectCapturesBetween(mixed, 'a', 'b').map((c) => c.id)).toEqual([])
        })
    })

    describe('selecting history', () => {
        let logic: ReturnType<typeof pageHistoryLogic>
        let captureLogic: ReturnType<typeof pageHistoryCaptureLogic>
        const dataLogic = heatmapDataLogic({ context: 'in-app' })

        beforeEach(async () => {
            initKeaTests()
            window.POSTHOG_APP_CONTEXT!.resource_access_control = {
                ...window.POSTHOG_APP_CONTEXT!.resource_access_control!,
                heatmap: AccessControlLevel.Editor,
            }
            jest.spyOn(api, 'queryHogQL').mockResolvedValue({ results: [] } as any)
            jest.spyOn(api.savedHeatmaps, 'list').mockImplementation(
                async () => ({ results: [saved], count: 1 }) as any
            )
            jest.spyOn(heatmapApi, 'savedRetrieve').mockImplementation(async () => saved)
            jest.spyOn(heatmapApi, 'savedScreenshotHistoryRetrieve').mockImplementation(async () =>
                historyResponse(captures)
            )
            router.actions.push('/heatmaps/hm_test')
            const sceneLogic = heatmapLogic({ id: 'hm_test' })
            sceneLogic.mount()
            await expectLogic(sceneLogic).toFinishAllListeners()
            dataLogic.actions.setCommonFilters({ date_from: '-7d' })
            dataLogic.actions.setWindowWidthOverride(1440)
            logic = pageHistoryLogic({ id: 'hm_test' })
            logic.mount()
            captureLogic = pageHistoryCaptureLogic({ id: 'hm_test' })
            captureLogic.mount()
            await expectLogic(logic, () => logic.actions.loadHistory()).toFinishAllListeners()
        })

        afterEach(() => {
            jest.useRealTimers()
            jest.restoreAllMocks()
        })

        it('scopes the overlay to the day, shows that day on its screenshot and locks the width', async () => {
            expect(captureLogic.values.completedCapture).toBeNull()
            await expectLogic(logic, () => logic.actions.selectCapture('cap-3')).toFinishAllListeners()

            expect(dataLogic.values.effectiveCommonFilters).toMatchObject({
                date_from: '2024-05-03',
                date_to: '2024-05-03',
            })
            expect(dataLogic.values.commonFilters).toEqual({ date_from: '-7d' })
            expect(dataLogic.values.dateRangeOverride).toMatchObject({ timestamp_from: '2024-05-03T00:00:00Z' })
            expect(dataLogic.values.widthOverride).toBe(1024)
            expect(heatmapLogic({ id: 'hm_test' }).values.lockedWidth).toBe(1024)
            const scene = heatmapLogic({ id: 'hm_test' })
            expect(scene.values.screenshotUrl).toBe(captures[0].content_url)
            scene.actions.setGeneratingScreenshot(true)
            scene.actions.setHistoryScreenshotStatus(captures[0].content_url!, true)
            scene.actions.setScreenshotLoaded(false)
            scene.actions.setScreenshotError('Current capture failed')
            expect(scene.values.previewUnavailable).toBe(false)
            expect(scene.values.previewError).toBeNull()
            expect(scene.values.screenshotLoaded).toBe(true)
            await expectLogic(logic, () => logic.actions.clearSelection()).toFinishAllListeners()
            expect(scene.values.previewError).toBe('Current capture failed')
            expect(scene.values.previewUnavailable).toBe(true)
        })

        it('previews a complete range without changing the applied view until Apply', async () => {
            await expectLogic(logic, () => logic.actions.selectCapture('cap-3')).toFinishAllListeners()
            logic.actions.openRangeEditor()
            logic.actions.setRangeDraft('cap-1', 'cap-3')
            expect(logic.values.rangeDraftBackground?.id).toBe('cap-3')
            expect(dataLogic.values.dateRangeOverride?.date_from).toBe('2024-05-03')
            logic.actions.setRangeEditorOpen(false)
            expect(dataLogic.values.dateRangeOverride?.date_from).toBe('2024-05-03')
            logic.actions.openRangeEditor()
            logic.actions.setRangeDraft('cap-1', 'cap-3')
            await expectLogic(logic, () => logic.actions.applyRangeDraft()).toFinishAllListeners()
            expect(logic.values.rangeEditorOpen).toBe(false)
            expect(dataLogic.values.dateRangeOverride).toMatchObject({
                date_from: '2024-05-01',
                date_to: '2024-05-03',
                timestamp_to: '2024-05-04T00:00:00Z',
            })
            await expectLogic(logic, () => logic.actions.browseCapture('cap-1')).toFinishAllListeners()
            expect(logic.values.selectedDateRange).toMatchObject({ date_from: '2024-05-01', date_to: '2024-05-01' })
        })

        it.each([{ width: 1440 }, { timezone: 'America/New_York' }])(
            'keeps the applied view when an incompatible range is drafted: %s',
            async (difference) => {
                await expectLogic(logic, () => {
                    logic.actions.loadHistorySuccess(
                        historyResponse([...captures, capture('cap-4', '2024-05-04', difference)])
                    )
                    logic.actions.selectCapture('cap-1')
                }).toFinishAllListeners()
                logic.actions.openRangeEditor()
                logic.actions.setRangeDraft('cap-1', 'cap-4')
                expect(logic.values.rangeDraftError).toContain('same screen width and timezone')
                await expectLogic(logic, () => logic.actions.applyRangeDraft()).toFinishAllListeners()
                expect(dataLogic.values.dateRangeOverride).toMatchObject({
                    date_from: '2024-05-01',
                    date_to: '2024-05-01',
                })
                expect(logic.values.rangeEditorOpen).toBe(true)
            }
        )

        it('preserves the shown day when a missing date is requested and explicitly identifies navigation gaps', async () => {
            await expectLogic(logic, () => logic.actions.selectCapture('cap-1')).toFinishAllListeners()
            await expectLogic(logic, () => logic.actions.browseCapture('cap-2')).toFinishAllListeners()
            expect(logic.values.missingCaptureDate).toBe('2024-05-02')
            expect(logic.values.missingDateAlternatives.map((capture) => capture.id)).toEqual(['cap-1', 'cap-3'])
            expect(logic.values.selectedBackground?.id).toBe('cap-1')
            await expectLogic(logic, () => logic.actions.navigateCapture('next')).toFinishAllListeners()
            expect(logic.values.selectedBackground?.id).toBe('cap-3')
            expect(logic.values.navigationNotice).toContain('Skipped 1 day')
            expect(logic.values.missingCaptureDate).toBeNull()
        })

        it.each(['unchanged metadata', 'failed replacement'])(
            'keeps an active area during %s refresh',
            async (state) => {
                await expectLogic(logic, () => logic.actions.selectCapture('cap-1')).toFinishAllListeners()
                const area = {
                    points: [{ x: 10, y: 20, target_fixed: false }],
                    expectedCount: 1,
                    clickX: 10,
                    clickY: 20,
                }
                await expectLogic(dataLogic, () => dataLogic.actions.setSelectedArea(area)).toFinishAllListeners()
                const scene = heatmapLogic({ id: 'hm_test' })
                scene.actions.setHistoryScreenshotStatus(scene.values.screenshotUrl!, true)
                const refreshed = capture(
                    'cap-1',
                    '2024-05-01',
                    state === 'failed replacement'
                        ? {
                              latest_request: {
                                  request_id: 'failed',
                                  state: 'failed',
                                  failure_cause: 'browserless_timeout',
                                  page_status: null,
                                  deadline: '2024-05-01T12:30:00Z',
                                  completed_at: '2024-05-01T12:05:00Z',
                              },
                          }
                        : {}
                )
                await expectLogic(logic, () =>
                    logic.actions.loadHistorySuccess(historyResponse([refreshed]))
                ).toFinishAllListeners()
                expect(dataLogic.values.selectedArea).toEqual(area)
                expect(dataLogic.values.showEventsPanel).toBe(true)
                expect(scene.values.screenshotLoaded).toBe(true)
            }
        )

        it('opens with recent captures and brings a chosen older date into view', async () => {
            const month = Array.from({ length: 21 }, (_, index) =>
                capture(`day-${index + 1}`, `2024-05-${String(index + 1).padStart(2, '0')}`)
            )
            await expectLogic(logic, () =>
                logic.actions.loadHistorySuccess(historyResponse(month))
            ).toFinishAllListeners()
            expect(logic.values.visibleCaptures.map((c) => c.id)).toEqual(month.slice(17).map((c) => c.id))
            await expectLogic(logic, () => logic.actions.selectCapture('day-1')).toFinishAllListeners()
            expect(logic.values.visibleCaptures.map((c) => c.id)).toEqual(month.slice(0, 1).map((c) => c.id))
            expect(logic.values.selectedBackground?.id).toBe('day-1')
        })

        it('refreshes the selected image after successful replacement', async () => {
            await expectLogic(logic, () => logic.actions.selectCapture('cap-1')).toFinishAllListeners()
            const area = { points: [{ x: 10, y: 20, target_fixed: false }], expectedCount: 1, clickX: 10, clickY: 20 }
            await expectLogic(dataLogic, () => dataLogic.actions.setSelectedArea(area)).toFinishAllListeners()
            const replacement = capture('cap-1', '2024-05-01', {
                content_url: '/replacement.jpg',
                revision: 'request-new',
            })
            await expectLogic(logic, () =>
                logic.actions.loadHistorySuccess(historyResponse([replacement]))
            ).toFinishAllListeners()
            expect(heatmapLogic({ id: 'hm_test' }).values.screenshotUrl).toBe('/replacement.jpg')
            expect(dataLogic.values.selectedArea).toBeNull()
            expect(dataLogic.values.showEventsPanel).toBe(false)
        })

        it('does not export a selected historical image through the action', async () => {
            await expectLogic(logic, () => logic.actions.selectCapture('cap-1')).toFinishAllListeners()
            const scene = heatmapLogic({ id: 'hm_test' })
            const exportAction = jest.spyOn(scene.actions, 'startHeatmapExport')
            scene.actions.exportHeatmap()
            expect(exportAction).not.toHaveBeenCalled()
        })

        it.each([
            ['no record of the request', null, null],
            ['a capture that finished', 'cap-3', null],
            ['a capture that failed', null, "couldn't finish"],
        ])(
            'clears loading when a request status poll fails, then reconciles %s',
            async (_label, completedId, error) => {
                jest.useFakeTimers()
                const poll = jest
                    .spyOn(heatmapApi, 'savedScreenshotHistoryRequestsRetrieve')
                    .mockRejectedValue(new Error('unavailable'))
                captureLogic.actions.pollRequest('request-1')
                expect(captureLogic.values.capturing).toBe(true)
                await jest.advanceTimersByTimeAsync(10000)
                expect(poll).toHaveBeenCalledWith('997', 'hm_test', 'request-1')
                expect(captureLogic.values.capturing).toBe(false)
                expect(captureLogic.values.captureStatusUnknown).toBe(true)
                expect(captureLogic.values.captureNowDisabledReason).toContain('Check the current capture')

                jest.useRealTimers()
                const reconciled =
                    completedId !== null
                        ? capture('cap-3', '2024-05-03', { revision: 'request-1' })
                        : error !== null
                          ? capture('cap-3', '2024-05-03', {
                                latest_request: {
                                    request_id: 'request-1',
                                    state: 'failed',
                                    failure_cause: 'browserless_timeout',
                                    page_status: null,
                                    deadline: '2024-05-03T12:30:00Z',
                                    completed_at: '2024-05-03T12:05:00Z',
                                },
                            })
                          : captures[0]
                jest.spyOn(heatmapApi, 'savedScreenshotHistoryRetrieve').mockResolvedValue(
                    historyResponse([reconciled, ...captures.slice(1)])
                )
                await expectLogic(logic, () => logic.actions.loadHistory()).toFinishAllListeners()
                expect(captureLogic.values.captureStatusUnknown).toBe(false)
                expect(captureLogic.values.completedCapture?.id ?? null).toBe(completedId)
                if (error) {
                    expect(captureLogic.values.captureError).toContain(error)
                } else {
                    expect(captureLogic.values.captureError).toBeNull()
                }
            }
        )

        it('offers a completed capture without changing the historical date being analyzed', async () => {
            await expectLogic(logic, () => logic.actions.selectCapture('cap-1')).toFinishAllListeners()
            jest.useFakeTimers()
            const completed = capture('cap-3', '2024-05-03', { revision: 'request-1' })
            jest.spyOn(heatmapApi, 'savedScreenshotHistoryRequestsRetrieve').mockResolvedValue({
                request_id: 'request-1',
                state: 'succeeded',
                deadline: '2024-05-03T12:30:00Z',
                completed_at: '2024-05-03T12:00:00Z',
                failure_cause: null,
                page_status: 200,
            })
            jest.spyOn(heatmapApi, 'savedScreenshotHistoryRetrieve').mockResolvedValue(
                historyResponse([completed, ...captures.slice(1)])
            )
            captureLogic.actions.pollRequest('request-1')
            await jest.advanceTimersByTimeAsync(10000)
            await jest.advanceTimersByTimeAsync(1000)
            expect(captureLogic.values.completedCapture?.id).toBe('cap-3')
            expect(logic.values.selectedBackground?.id).toBe('cap-1')
            expect(captureLogic.values.capturing).toBe(false)
        })

        it.each([
            ['rate limited', new ApiError('Throttled', 429, new Headers({ 'Retry-After': '600' })), '10 minutes'],
            ['unavailable', new Error('Unavailable'), 'Try again later'],
        ])('clears capture loading and explains a creation failure: %s', async (_label, error, message) => {
            jest.spyOn(heatmapApi, 'savedScreenshotHistoryCaptureCreate').mockRejectedValue(error)
            await expectLogic(captureLogic, () => captureLogic.actions.captureNow()).toFinishAllListeners()
            expect(captureLogic.values.capturing).toBe(false)
            expect(captureLogic.values.captureError).toContain(message)
        })

        it('resumes polling a pending capture when the strip mounts after history loaded', async () => {
            const pending = capture('cap-3', '2024-05-03', {
                latest_request: {
                    request_id: 'request-1',
                    state: 'running',
                    failure_cause: null,
                    page_status: null,
                    deadline: '2024-05-03T12:30:00Z',
                    completed_at: null,
                },
            })
            captureLogic.unmount()
            await expectLogic(logic, () =>
                logic.actions.loadHistorySuccess(historyResponse([pending, ...captures.slice(1)]))
            ).toFinishAllListeners()

            captureLogic = pageHistoryCaptureLogic({ id: 'hm_test' })
            captureLogic.mount()

            expect(captureLogic.values.capturing).toBe(true)
        })

        it('ignores a capture request that resolves after the page changed', async () => {
            let resolveCreate: (
                value: Awaited<ReturnType<typeof heatmapApi.savedScreenshotHistoryCaptureCreate>>
            ) => void
            jest.spyOn(heatmapApi, 'savedScreenshotHistoryCaptureCreate').mockImplementation(
                () => new Promise((resolve) => (resolveCreate = resolve))
            )
            captureLogic.actions.captureNow()
            expect(captureLogic.values.capturing).toBe(true)

            logic.actions.pageChanged()
            resolveCreate!({ request_id: 'request-old' } as Awaited<
                ReturnType<typeof heatmapApi.savedScreenshotHistoryCaptureCreate>
            >)
            await expectLogic(captureLogic).toFinishAllListeners()

            expect(captureLogic.values.capturing).toBe(false)
        })

        it('picks up a capture the server accepted when the create response was lost', async () => {
            const accepted = capture('cap-3', '2024-05-03', {
                latest_request: {
                    request_id: 'request-1',
                    state: 'queued',
                    failure_cause: null,
                    page_status: null,
                    deadline: '2024-05-03T12:30:00Z',
                    completed_at: null,
                },
            })
            jest.spyOn(heatmapApi, 'savedScreenshotHistoryCaptureCreate').mockRejectedValue(new Error('Network error'))
            jest.spyOn(heatmapApi, 'savedScreenshotHistoryRetrieve').mockResolvedValue(
                historyResponse([accepted, ...captures.slice(1)])
            )

            await expectLogic(captureLogic, () => captureLogic.actions.captureNow()).toFinishAllListeners()
            await expectLogic(logic).toFinishAllListeners()

            expect(captureLogic.values.capturing).toBe(true)
            expect(captureLogic.values.captureError).toBeNull()
        })

        it('stops polling when navigation unmounts the history logic', async () => {
            jest.useFakeTimers()
            const poll = jest.spyOn(heatmapApi, 'savedScreenshotHistoryRequestsRetrieve')
            captureLogic.actions.pollRequest('request-1')
            captureLogic.unmount()
            await jest.advanceTimersByTimeAsync(10000)
            expect(poll).not.toHaveBeenCalled()
        })

        it('keeps history selections separate between projects', async () => {
            const other = pageHistoryLogic({ id: 'hm_test', teamId: 998 })
            other.mount()
            await expectLogic(other, () => other.actions.loadHistory()).toFinishAllListeners()
            await expectLogic(logic, () => logic.actions.selectCapture('cap-1')).toFinishAllListeners()
            expect(other.values.anchorId).toBeNull()
            await expectLogic(other, () => other.actions.selectCapture('cap-3')).toFinishAllListeners()
            await expectLogic(logic, () =>
                logic.actions.loadHistorySuccess(historyResponse(captures))
            ).toFinishAllListeners()
            expect(dataLogic.values.historyView?.owner).toBe('998:hm_test')
            expect(logic.values.anchorId).toBeNull()
            logic.unmount()
            expect(dataLogic.values.dateRangeOverride?.date_from).toBe('2024-05-03')
            expect(dataLogic.values.historyView?.owner).toBe('998:hm_test')
            other.unmount()
            expect(dataLogic.values.dateRangeOverride).toBeNull()
        })

        it('loads history once the page history flag turns on after mount', async () => {
            const late = pageHistoryLogic({ id: 'hm_test', teamId: 998 })
            late.mount()
            await expectLogic(late).toFinishAllListeners()
            expect(late.values.history).toBeNull()

            await expectLogic(late, () =>
                featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.HEATMAPS_PAGE_HISTORY]: true })
            ).toFinishAllListeners()

            expect(late.values.history).toEqual(historyResponse(captures))
            late.unmount()
        })

        it('drops the previous page history when the saved page changes', async () => {
            featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.HEATMAPS_PAGE_HISTORY]: true })
            await expectLogic(logic, () => logic.actions.selectCapture('cap-1')).toFinishAllListeners()
            jest.spyOn(heatmapApi, 'savedScreenshotHistoryRetrieve').mockRejectedValue(new Error('unavailable'))
            const scene = heatmapLogic({ id: 'hm_test' })
            await expectLogic(logic, () =>
                scene.actions.setSavedSettings({ ...scene.values.savedSettings!, url: 'https://example.com/new-page' })
            ).toFinishAllListeners()
            await expectLogic(logic, () => logic.actions.browseCapture('cap-3')).toFinishAllListeners()

            expect(logic.values.historyLoadFailed).toBe(true)
            expect(logic.values.captures).toEqual([])
            expect(logic.values.isSelectionActive).toBe(false)
            expect(dataLogic.values.historyView).toBeNull()
        })

        it('restores the current view and reloads history when a cached day has expired', async () => {
            const expired = capture('cap-1', '2024-05-01', { expires_at: dayjs().subtract(1, 'minute').toISOString() })
            await expectLogic(logic, () =>
                logic.actions.loadHistorySuccess(historyResponse([captures[0], expired]))
            ).toFinishAllListeners()
            await expectLogic(logic, () => logic.actions.browseCapture('cap-1')).toFinishAllListeners()

            expect(logic.values.isSelectionActive).toBe(false)
            expect(dataLogic.values.historyView).toBeNull()
            expect(logic.values.navigationNotice).toContain('no longer available')
            expect(logic.values.history).toEqual(historyResponse(captures))
        })

        it.each(['cap-1', 'cap-3'])(
            'explains recovery when a combined-range endpoint expires: %s',
            async (expiredId) => {
                await expectLogic(logic, () => logic.actions.setSelectionRange('cap-1', 'cap-3')).toFinishAllListeners()
                dataLogic.actions.setCommonFilters({ date_from: '-30d', filter_test_accounts: true })
                await expectLogic(logic, () =>
                    logic.actions.loadHistorySuccess(
                        historyResponse(captures.filter((capture) => capture.id !== expiredId))
                    )
                ).toFinishAllListeners()
                expect(logic.values.isSelectionActive).toBe(false)
                expect(logic.values.navigationNotice).toContain('no longer available')
                expect(logic.values.historyExpanded).toBe(true)
                expect(dataLogic.values.dateRangeOverride).toBeNull()
                expect(dataLogic.values.commonFilters).toEqual({ date_from: '-30d', filter_test_accounts: true })
            }
        )

        it.each(['exit history', 'edit the page URL', 'switch to an iframe'])(
            'restores current filters and width when users %s',
            async (action) => {
                const sceneLogic = heatmapLogic({ id: 'hm_test' })
                const currentScreenshotUrl = sceneLogic.values.screenshotUrl
                await expectLogic(logic, () => logic.actions.selectCapture('cap-1')).toFinishAllListeners()
                dataLogic.actions.setCommonFilters({ date_from: '-30d', filter_test_accounts: true })
                await expectLogic(logic, () => {
                    if (action === 'edit the page URL') {
                        sceneLogic.actions.setPageUrlDraft('https://example.com/new-page')
                    } else if (action === 'switch to an iframe') {
                        sceneLogic.actions.setType('iframe')
                    } else {
                        logic.actions.clearSelection()
                    }
                }).toFinishAllListeners()

                expect(logic.values.isSelectionActive).toBe(false)
                expect(dataLogic.values.commonFilters).toEqual({ date_from: '-30d', filter_test_accounts: true })
                expect(dataLogic.values.dateRangeOverride).toBeNull()
                expect(dataLogic.values.widthOverride).toBe(1440)
                expect(sceneLogic.values.lockedWidth).toBeNull()
                expect(sceneLogic.values.screenshotUrl).toBe(currentScreenshotUrl)
            }
        )
    })
})
