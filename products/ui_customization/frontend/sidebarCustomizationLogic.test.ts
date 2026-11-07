import { expectLogic } from 'kea-test-utils'

import { toast } from '@posthog/quill'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { getCurrentTeamIdOrNone, getCurrentUserIdOrNone } from 'lib/utils/getAppContext'
import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'

import { initKeaTests } from '~/test/init'

import type { AnalyticsSidebarApi } from './generated/api.schemas'
import { SidebarCustomizationProps, sidebarCustomizationLogic } from './sidebarCustomizationLogic'

const defaults: AnalyticsSidebarApi = { customized: false, layout: { version: 1, sections: [] } }
const custom: AnalyticsSidebarApi = {
    customized: true,
    layout: { version: 1, sections: [{ id: 'saved', title: 'Saved', items: [] }] },
}

function deferred<T>(): { promise: Promise<T>; resolve: (value: T) => void; reject: (error: Error) => void } {
    let resolve!: (value: T) => void
    let reject!: (error: Error) => void
    const promise = new Promise<T>((yes, no) => {
        resolve = yes
        reject = no
    })
    return { promise, resolve, reject }
}

function configuration(): SidebarCustomizationProps {
    return {
        projectId: String(getCurrentTeamIdOrNone()),
        userId: getCurrentUserIdOrNone()!,
        configuration: {
            context: 'analytics_sidebar',
            defaults,
            storageKey: 'customization-test',
            resetEvent: 'analytics sidebar reset',
            retrieve: jest.fn().mockResolvedValue(custom),
            reset: jest.fn().mockResolvedValue(defaults),
            restore: jest.fn().mockResolvedValue(custom),
        },
    }
}

describe('sidebarCustomizationLogic lifetime', () => {
    beforeEach(() => {
        localStorage.clear()
        initKeaTests()
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.UI_CUSTOMIZATION]: true })
    })
    afterEach(() => jest.restoreAllMocks())

    it.each(['load', 'reset', 'restore'] as const)(
        'reconciles %s across pane unmount and remount without an extra stale read',
        async (operation) => {
            const props = configuration()
            const logic = sidebarCustomizationLogic(props)
            const leave = logic.mount()
            await expectLogic(logic).toFinishAllListeners()
            const pending = deferred<AnalyticsSidebarApi>()
            const method = operation === 'load' ? 'retrieve' : operation
            jest.spyOn(props.configuration, method).mockReturnValueOnce(pending.promise)
            const success = jest.spyOn(toast, 'success')
            const result =
                operation === 'load'
                    ? logic.asyncActions.loadSidebar()
                    : operation === 'reset'
                      ? logic.asyncActions.resetSidebar(custom.layout)
                      : logic.asyncActions.restoreSidebar(custom.layout)
            leave()
            expect(logic.isMounted()).toBe(true)
            const remounted = sidebarCustomizationLogic(props)
            const leaveAgain = remounted.mount()
            expect(remounted.values.shownSidebar).toEqual(custom)
            expect(props.configuration.retrieve).toHaveBeenCalledTimes(operation === 'load' ? 2 : 1)
            pending.resolve(defaults)
            await result
            expect(remounted.values.shownSidebar).toEqual(defaults)
            expect(remounted.values.sidebarLoading).toBe(false)
            if (operation === 'reset') {
                expect(success).toHaveBeenCalledTimes(1)
                await success.mock.calls[0][0].action?.onClick()
                expect(remounted.values.shownSidebar).toEqual(custom)
            }
            leaveAgain()
            expect(remounted.isMounted()).toBe(false)
        }
    )

    it.each(['project', 'user', 'flag'] as const)(
        'does not reconcile or send a queued write after the %s changes',
        async (guard) => {
            const props = configuration()
            const logic = sidebarCustomizationLogic(props)
            const leave = logic.mount()
            await expectLogic(logic).toFinishAllListeners()
            const pending = deferred<AnalyticsSidebarApi>()
            jest.spyOn(props.configuration, 'reset').mockReturnValueOnce(pending.promise)
            const success = jest.spyOn(toast, 'success')
            const resetting = logic.asyncActions.resetSidebar(custom.layout)
            await Promise.resolve()
            const restoring = logic.asyncActions.restoreSidebar(custom.layout)
            if (guard === 'project') {
                teamLogic.actions.loadCurrentTeamSuccess({ ...teamLogic.values.currentTeam!, project_id: 12345 })
            } else if (guard === 'user') {
                userLogic.actions.loadUserSuccess(null)
            } else {
                featureFlagLogic.actions.setFeatureFlags([], {})
            }
            leave()
            pending.resolve(defaults)
            await Promise.all([resetting, restoring])
            expect(props.configuration.restore).not.toHaveBeenCalled()
            expect(success).not.toHaveBeenCalled()
            expect(logic.isMounted()).toBe(false)
        }
    )

    it('recovers a failed reset after remount and releases its retained mount', async () => {
        const props = configuration()
        const logic = sidebarCustomizationLogic(props)
        const leave = logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        const pending = deferred<AnalyticsSidebarApi>()
        jest.spyOn(props.configuration, 'reset').mockReturnValueOnce(pending.promise)
        const reset = logic.asyncActions.resetSidebar(custom.layout)
        leave()
        const leaveAgain = sidebarCustomizationLogic(props).mount()
        pending.reject(new Error('Unavailable'))
        await reset
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.shownSidebar).toEqual(custom)
        expect(logic.values.sidebarLoading).toBe(false)
        await logic.asyncActions.resetSidebar(custom.layout)
        expect(logic.values.shownSidebar).toEqual(defaults)
        leaveAgain()
        expect(logic.isMounted()).toBe(false)
    })
})
