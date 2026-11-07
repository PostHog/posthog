import { expectLogic } from 'kea-test-utils'

import { toast } from '@posthog/quill'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { fileSystemEntryToAnalytics } from 'scenes/analytics/analyticsUtils'

import { projectTreeDataLogic } from '~/layout/panel-layout/ProjectTree/projectTreeDataLogic'
import defaultSidebarFixture from '~/mocks/fixtures/api/today_analytics_sidebar.json'
import { useMocks } from '~/mocks/jest'
import { recentItemsModel } from '~/models/recentItemsModel'
import { FileSystemEntry } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import * as sidebarApi from 'products/ui_customization/frontend/generated/api'
import type { AnalyticsSidebarApi } from 'products/ui_customization/frontend/generated/api.schemas'
import { sidebarCustomizationLogic } from 'products/ui_customization/frontend/sidebarCustomizationLogic'

import { DEFAULT_ANALYTICS_SIDEBAR, analyticsSidebarProps } from './analyticsSidebarConfiguration'
import { DEFAULT_COLLAPSED_SECTIONS, todayAnalyticsLogic } from './todayAnalyticsLogic'

const CUSTOM_SIDEBAR: AnalyticsSidebarApi = {
    customized: true,
    layout: {
        version: 1,
        sections: [
            { id: 'growth', title: 'Growth', items: [{ type: 'metric', insight: 'aB3dE5fG', label: 'Signups' }] },
        ],
    },
}
const DEFAULT_SIDEBAR: AnalyticsSidebarApi = {
    customized: false,
    layout: { version: 1, sections: [{ id: 'pinned', title: 'Pinned', items: [{ type: 'list', source: 'pinned' }] }] },
}

function deferred<T>(): { promise: Promise<T>; resolve: (value: T) => void; reject: (error: Error) => void } {
    let resolve!: (value: T) => void
    let reject!: (error: Error) => void
    const promise = new Promise<T>((resolvePromise, rejectPromise) => {
        resolve = resolvePromise
        reject = rejectPromise
    })
    return { promise, resolve, reject }
}

describe('todayAnalyticsLogic', () => {
    afterEach(() => jest.restoreAllMocks())
    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team_id/task_channels/': [],
                '/api/projects/:team_id/canvases/': { results: [], next: null },
                '/api/projects/:team_id/notebooks/': { results: [], next: null },
                '/api/projects/:team_id/dashboards/': { results: [], next: null },
                '/api/projects/:team_id/insights/': { results: [], next: null },
                '/api/projects/:team_id/file_system_shortcut/': {
                    results: [{ id: 'sc-pinned', type: 'insight/trends', path: 'Retention', ref: 'i2' }],
                },
                '/api/projects/:team_id/ui_customization/analytics_sidebar/': CUSTOM_SIDEBAR,
            },
            put: { '/api/projects/:team_id/ui_customization/analytics_sidebar/': CUSTOM_SIDEBAR },
            delete: { '/api/projects/:team_id/ui_customization/analytics_sidebar/': DEFAULT_SIDEBAR },
        })
        localStorage.clear()
        initKeaTests()
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.UI_CUSTOMIZATION]: true })
        recentItemsModel.mount()
    })

    it('ignores a cached custom layout and makes no requests while customization is disabled', async () => {
        featureFlagLogic.actions.setFeatureFlags([], {})
        const read = jest.spyOn(sidebarApi, 'uiCustomizationAnalyticsSidebarRetrieve')
        const reset = jest.spyOn(sidebarApi, 'uiCustomizationAnalyticsSidebarDestroy')
        const restore = jest.spyOn(sidebarApi, 'uiCustomizationAnalyticsSidebarUpdate')
        const logic = sidebarCustomizationLogic(analyticsSidebarProps())
        logic.mount()
        logic.actions.requestSidebarSuccess(CUSTOM_SIDEBAR)
        await logic.asyncActions.loadSidebar()
        await logic.asyncActions.resetSidebar(CUSTOM_SIDEBAR.layout)
        await logic.asyncActions.restoreSidebar(CUSTOM_SIDEBAR.layout)

        expect(logic.values.savedSidebar).toEqual(CUSTOM_SIDEBAR)
        expect(logic.values.shownSidebar).toEqual(DEFAULT_ANALYTICS_SIDEBAR)
        expect(read).not.toHaveBeenCalled()
        expect(reset).not.toHaveBeenCalled()
        expect(restore).not.toHaveBeenCalled()
    })

    it('loads customization when feature flags arrive after mount', async () => {
        featureFlagLogic.actions.setFeatureFlags([], {})
        const logic = sidebarCustomizationLogic(analyticsSidebarProps())
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.shownSidebar).toEqual(DEFAULT_ANALYTICS_SIDEBAR)

        await expectLogic(logic, () => {
            featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.UI_CUSTOMIZATION]: true })
        }).toDispatchActions(['requestSidebarSuccess'])
        expect(logic.values.shownSidebar).toEqual(CUSTOM_SIDEBAR)
    })

    it.each([false, true])(
        'discards an in-flight response after disabling customization, failure=%s',
        async (fails) => {
            const logic = sidebarCustomizationLogic(analyticsSidebarProps())
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()
            const read = deferred<AnalyticsSidebarApi>()
            jest.spyOn(sidebarApi, 'uiCustomizationAnalyticsSidebarRetrieve').mockReturnValueOnce(read.promise)
            const reading = logic.asyncActions.loadSidebar()
            featureFlagLogic.actions.setFeatureFlags([], {})
            fails ? read.reject(new Error('Old request failed')) : read.resolve(DEFAULT_SIDEBAR)
            await reading

            expect(logic.values.savedSidebar).toEqual(CUSTOM_SIDEBAR)
            expect(logic.values.shownSidebar).toEqual(DEFAULT_ANALYTICS_SIDEBAR)
            expect(logic.values.sidebarFailed).toBe(false)
        }
    )

    it('skips queued writes when disabled and recovers after re-enabling', async () => {
        const logic = sidebarCustomizationLogic(analyticsSidebarProps())
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        const reset = deferred<AnalyticsSidebarApi>()
        const destroy = jest
            .spyOn(sidebarApi, 'uiCustomizationAnalyticsSidebarDestroy')
            .mockReturnValueOnce(reset.promise)
        const restore = jest.spyOn(sidebarApi, 'uiCustomizationAnalyticsSidebarUpdate')
        const success = jest.spyOn(toast, 'success')
        const resetting = logic.asyncActions.resetSidebar(CUSTOM_SIDEBAR.layout)
        await Promise.resolve()
        expect(destroy).toHaveBeenCalledTimes(1)
        const restoring = logic.asyncActions.restoreSidebar(CUSTOM_SIDEBAR.layout)
        featureFlagLogic.actions.setFeatureFlags([], {})
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.UI_CUSTOMIZATION]: true })
        reset.resolve(DEFAULT_SIDEBAR)
        await Promise.all([resetting, restoring])
        await expectLogic(logic).toFinishAllListeners()

        expect(restore).not.toHaveBeenCalled()
        expect(success).not.toHaveBeenCalled()
        expect(logic.values.shownSidebar).toEqual(CUSTOM_SIDEBAR)
        expect(logic.values.sidebarLoading).toBe(false)
    })

    it.each([false, true])('shows the default while the first request is pending, failure=%s', async (fails) => {
        let startRequest!: () => void
        const requestStarted = new Promise<void>((resolve) => (startRequest = resolve))
        let finishRequest!: () => void
        const requestReleased = new Promise<void>((resolve) => (finishRequest = resolve))
        useMocks({
            get: {
                '/api/projects/:team_id/ui_customization/analytics_sidebar/': async () => {
                    startRequest()
                    await requestReleased
                    return fails ? [503, { detail: 'Unavailable' }] : [200, CUSTOM_SIDEBAR]
                },
            },
        })
        const logic = sidebarCustomizationLogic(analyticsSidebarProps())
        logic.mount()
        await requestStarted

        expect(DEFAULT_ANALYTICS_SIDEBAR).toEqual(defaultSidebarFixture)
        expect(logic.values.sidebarLayout).toEqual(DEFAULT_ANALYTICS_SIDEBAR.layout)
        expect(logic.values.sidebarCustomized).toBe(false)

        finishRequest()
        await expectLogic(logic).toDispatchActions([fails ? 'requestSidebarFailure' : 'requestSidebarSuccess'])
        expect(logic.values.sidebarFailed).toBe(fails)
        expect(logic.values.sidebarLayout).toEqual(fails ? DEFAULT_ANALYTICS_SIDEBAR.layout : CUSTOM_SIDEBAR.layout)
        expect(logic.values.sidebarCustomized).toBe(!fails)
    })

    it.each([
        ['reset', false],
        ['reset', true],
        ['restore', false],
        ['restore', true],
    ] as const)('keeps %s and its cache when an older GET finishes, failure=%s', async (operation, fails) => {
        const logic = sidebarCustomizationLogic(analyticsSidebarProps())
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        const expected = operation === 'reset' ? DEFAULT_SIDEBAR : CUSTOM_SIDEBAR
        const stale = operation === 'reset' ? CUSTOM_SIDEBAR : DEFAULT_SIDEBAR
        const read = deferred<AnalyticsSidebarApi>()
        jest.spyOn(sidebarApi, 'uiCustomizationAnalyticsSidebarRetrieve').mockReturnValueOnce(read.promise)
        const reading = logic.asyncActions.loadSidebar()

        await (operation === 'reset'
            ? logic.asyncActions.resetSidebar(CUSTOM_SIDEBAR.layout)
            : logic.asyncActions.restoreSidebar(CUSTOM_SIDEBAR.layout))
        expect(logic.values.savedSidebar).toEqual(expected)

        fails ? read.reject(new Error('Old request failed')) : read.resolve(stale)
        await reading
        expect(logic.values.shownSidebar).toEqual(expected)
        expect(logic.values.savedSidebar).toEqual(expected)
        expect(logic.values.sidebarFailed).toBe(false)
        expect(logic.values.sidebarLoading).toBe(false)
    })

    it.each(['reset', 'restore'] as const)('waits for %s before reloading during the write', async (operation) => {
        const logic = sidebarCustomizationLogic(analyticsSidebarProps())
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        const expected = operation === 'reset' ? DEFAULT_SIDEBAR : CUSTOM_SIDEBAR
        const write = deferred<AnalyticsSidebarApi>()
        const successToast = jest.spyOn(toast, 'success')
        const read = jest.spyOn(sidebarApi, 'uiCustomizationAnalyticsSidebarRetrieve').mockResolvedValue(expected)
        const writer = jest
            .spyOn(
                sidebarApi,
                operation === 'reset'
                    ? 'uiCustomizationAnalyticsSidebarDestroy'
                    : 'uiCustomizationAnalyticsSidebarUpdate'
            )
            .mockReturnValueOnce(write.promise)
        const writing =
            operation === 'reset'
                ? logic.asyncActions.resetSidebar(CUSTOM_SIDEBAR.layout)
                : logic.asyncActions.restoreSidebar(CUSTOM_SIDEBAR.layout)
        await expectLogic(logic).toDispatchActions([operation === 'reset' ? 'resetSidebar' : 'restoreSidebar'])
        expect(writer).toHaveBeenCalledTimes(1)

        logic.actions.loadSidebar()
        logic.actions.loadSidebar()
        expect(read).not.toHaveBeenCalled()
        expect(logic.values.sidebarLoading).toBe(true)

        write.resolve(expected)
        await writing
        await expectLogic(logic).toFinishAllListeners()
        expect(read).toHaveBeenCalledTimes(1)
        expect(logic.values.shownSidebar).toEqual(expected)
        expect(logic.values.savedSidebar).toEqual(expected)
        expect(logic.values.sidebarLoading).toBe(false)
        if (operation === 'reset') {
            expect(successToast).toHaveBeenCalledWith(
                expect.objectContaining({ title: 'Sidebar reset to the default' })
            )
        }
    })

    it.each([false, true])('finishes queued writes in order after an older reset, failure=%s', async (fails) => {
        const logic = sidebarCustomizationLogic(analyticsSidebarProps())
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        const reset = deferred<AnalyticsSidebarApi>()
        jest.spyOn(sidebarApi, 'uiCustomizationAnalyticsSidebarDestroy').mockReturnValueOnce(reset.promise)
        const restore = jest
            .spyOn(sidebarApi, 'uiCustomizationAnalyticsSidebarUpdate')
            .mockResolvedValue(CUSTOM_SIDEBAR)
        jest.spyOn(sidebarApi, 'uiCustomizationAnalyticsSidebarRetrieve').mockResolvedValue(CUSTOM_SIDEBAR)
        const errorToast = jest.spyOn(toast, 'error')
        const resetting = logic.asyncActions.resetSidebar(CUSTOM_SIDEBAR.layout)
        const restoring = logic.asyncActions.restoreSidebar(CUSTOM_SIDEBAR.layout)
        logic.actions.loadSidebar()
        expect(restore).not.toHaveBeenCalled()

        fails ? reset.reject(new Error('Old reset failed')) : reset.resolve(DEFAULT_SIDEBAR)
        await Promise.all([resetting, restoring])
        await expectLogic(logic).toFinishAllListeners()
        expect(restore).toHaveBeenCalledTimes(1)
        expect(logic.values.shownSidebar).toEqual(CUSTOM_SIDEBAR)
        expect(logic.values.savedSidebar).toEqual(CUSTOM_SIDEBAR)
        expect(logic.values.sidebarFailed).toBe(false)
        expect(logic.values.sidebarLoading).toBe(false)
        expect(errorToast).not.toHaveBeenCalled()
    })

    it.each(['reset', 'restore'] as const)('reloads server state after the current %s fails', async (operation) => {
        const logic = sidebarCustomizationLogic(analyticsSidebarProps())
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        const write = deferred<AnalyticsSidebarApi>()
        jest.spyOn(
            sidebarApi,
            operation === 'reset' ? 'uiCustomizationAnalyticsSidebarDestroy' : 'uiCustomizationAnalyticsSidebarUpdate'
        ).mockReturnValueOnce(write.promise)
        const read = jest.spyOn(sidebarApi, 'uiCustomizationAnalyticsSidebarRetrieve').mockResolvedValue(CUSTOM_SIDEBAR)
        const errorToast = jest.spyOn(toast, 'error')
        const writing =
            operation === 'reset'
                ? logic.asyncActions.resetSidebar(CUSTOM_SIDEBAR.layout)
                : logic.asyncActions.restoreSidebar(CUSTOM_SIDEBAR.layout)
        write.reject(new Error('Current write failed'))
        await writing
        await expectLogic(logic).toFinishAllListeners()

        expect(read).toHaveBeenCalledTimes(1)
        expect(errorToast).toHaveBeenCalled()
        expect(logic.values.shownSidebar).toEqual(CUSTOM_SIDEBAR)
        expect(logic.values.savedSidebar).toEqual(CUSTOM_SIDEBAR)
        expect(logic.values.sidebarFailed).toBe(false)
        expect(logic.values.sidebarLoading).toBe(false)
    })

    it('shows a completed reset when the queued restore fails', async () => {
        const logic = sidebarCustomizationLogic(analyticsSidebarProps())
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        const reset = deferred<AnalyticsSidebarApi>()
        jest.spyOn(sidebarApi, 'uiCustomizationAnalyticsSidebarDestroy').mockReturnValueOnce(reset.promise)
        jest.spyOn(sidebarApi, 'uiCustomizationAnalyticsSidebarUpdate').mockRejectedValueOnce(
            new Error('Restore failed')
        )
        const read = jest
            .spyOn(sidebarApi, 'uiCustomizationAnalyticsSidebarRetrieve')
            .mockResolvedValue(DEFAULT_SIDEBAR)
        const resetting = logic.asyncActions.resetSidebar(CUSTOM_SIDEBAR.layout)
        const restoring = logic.asyncActions.restoreSidebar(CUSTOM_SIDEBAR.layout)

        reset.resolve(DEFAULT_SIDEBAR)
        await Promise.all([resetting, restoring])
        await expectLogic(logic).toFinishAllListeners()
        expect(read).toHaveBeenCalledTimes(1)
        expect(logic.values.shownSidebar).toEqual(DEFAULT_SIDEBAR)
        expect(logic.values.savedSidebar).toEqual(DEFAULT_SIDEBAR)
        expect(logic.values.sidebarLoading).toBe(false)
    })

    it('shows the persisted layout on remount until the server replaces it', async () => {
        const props = analyticsSidebarProps()
        const logic = sidebarCustomizationLogic(props)
        const unmount = logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        unmount()

        const read = deferred<AnalyticsSidebarApi>()
        jest.spyOn(sidebarApi, 'uiCustomizationAnalyticsSidebarRetrieve').mockReturnValueOnce(read.promise)
        const remounted = sidebarCustomizationLogic(props)
        remounted.mount()
        expect(remounted.values.shownSidebar).toEqual(CUSTOM_SIDEBAR)
        expect(remounted.values.sidebarLoading).toBe(true)

        read.resolve(DEFAULT_SIDEBAR)
        await expectLogic(remounted).toFinishAllListeners()
        expect(remounted.values.shownSidebar).toEqual(DEFAULT_SIDEBAR)
        expect(remounted.values.savedSidebar).toEqual(DEFAULT_SIDEBAR)
    })

    it('starts with every section open, and remembers a toggled section', () => {
        const logic = todayAnalyticsLogic()
        logic.mount()
        expect(logic.values.collapsedSections).toEqual(DEFAULT_COLLAPSED_SECTIONS)
        expect(logic.values.collapsedSections).toEqual([])

        logic.actions.toggleSection('monitor')
        expect(logic.values.collapsedSections).toEqual(['monitor'])

        logic.unmount()
        const remounted = todayAnalyticsLogic()
        remounted.mount()
        expect(remounted.values.collapsedSections).toEqual(['monitor'])
    })

    it('lists recently viewed analytics up to the limit, leaving out pinned items, and clears them when the shared list loads empty', async () => {
        const logic = todayAnalyticsLogic()
        logic.mount()
        await expectLogic(projectTreeDataLogic).toDispatchActions(['loadShortcutsSuccess'])
        const row = (type: string, ref: string, name: string): FileSystemEntry =>
            ({ id: `fs-${ref}`, type, ref, path: `Unfiled/${name}`, meta: {} }) as FileSystemEntry

        await expectLogic(logic, () =>
            logic.actions.storeRecentAnalytics(
                [row('insight', 'i1', 'Signups'), row('insight', 'i2', 'Retention')].flatMap(
                    (entry) => fileSystemEntryToAnalytics(entry) ?? []
                )
            )
        )
            .toDispatchActions(['storeRecentAnalytics'])
            .toNotHaveDispatchedActions(['storeRecentAnalytics'])
        expect(logic.values.recentAnalytics.map((item) => item.name)).toEqual(['Signups'])

        recentItemsModel.actions.loadRecentsSuccess([
            row('insight', 'i1', 'Signups'),
            row('insight', 'i2', 'Retention'),
            row('feature_flag', 'f1', 'New nav'),
            row('dashboard', '7', 'Revenue'),
            row('dashboard', '8', 'Costs'),
        ])
        expect(logic.values.recentAnalytics.map((item) => [item.type, item.name])).toEqual([
            ['dashboard', 'Costs'],
            ['dashboard', 'Revenue'],
            ['insight', 'Signups'],
        ])

        recentItemsModel.actions.loadRecentsSuccess([])
        expect(logic.values.recentAnalytics).toEqual([])
    })

    it.each([false, true])('restores the saved layout through Undo, left pane=%s', async (leftPane) => {
        const successToast = jest.spyOn(toast, 'success')
        let logic = sidebarCustomizationLogic(analyticsSidebarProps())
        logic.mount()
        const shown = (): [boolean, string[] | undefined] => [
            logic.values.sidebarCustomized,
            logic.values.sidebarLayout?.sections.map((section) => section.id),
        ]
        await expectLogic(logic).toDispatchActions(['requestSidebarSuccess'])
        const loaded = shown()

        await expectLogic(logic, () => logic.actions.resetSidebar(CUSTOM_SIDEBAR.layout)).toDispatchActions([
            'requestSidebarSuccess',
        ])
        const reset = shown()

        const undo = successToast.mock.calls.find(([options]) => options.title === 'Sidebar reset to the default')?.[0]
            .action
        expect(undo?.label).toBe('Undo')
        const projectId = String(logic.values.currentProjectId)
        const restore = jest
            .spyOn(sidebarApi, 'uiCustomizationAnalyticsSidebarUpdate')
            .mockResolvedValue(CUSTOM_SIDEBAR)
        if (leftPane) {
            logic.unmount()
        }
        await undo?.onClick()
        await expectLogic(logic).toFinishAllListeners()
        expect(restore).toHaveBeenCalledWith(projectId, { layout: CUSTOM_SIDEBAR.layout })
        expect(logic.isMounted()).toBe(!leftPane)
        if (leftPane) {
            logic = sidebarCustomizationLogic(analyticsSidebarProps())
            logic.mount()
        }
        await expectLogic(logic).toFinishAllListeners()

        expect([loaded, reset, shown()]).toEqual([
            [true, ['growth']],
            [false, ['pinned']],
            [true, ['growth']],
        ])
    })
})
