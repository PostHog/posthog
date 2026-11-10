import { act, cleanup, renderHook } from '@testing-library/react'
import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { toast } from '@posthog/quill'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { getCurrentTeamIdOrNone, getCurrentUserIdOrNone } from 'lib/utils/getAppContext'
import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'

import { initKeaTests } from '~/test/init'

import { resolveToolCall, toolStreamEventsLogic } from 'products/posthog_ai/frontend/api/logics'
import type { ToolStreamEvent } from 'products/posthog_ai/frontend/api/types'

import type { CustomizationApi } from './generated/api.schemas'
import { SidebarAgentListener } from './SidebarAgentListener'
import { SidebarCustomizationProps, sidebarCustomizationLogic } from './sidebarCustomizationLogic'

const defaults: CustomizationApi = { customized: false, layout: { version: 1, sections: [] } }
const custom: CustomizationApi = {
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

function execEvent(phase: ToolStreamEvent['phase'], context: string): ToolStreamEvent {
    const invocation: ToolStreamEvent['invocation'] = {
        toolCallId: 'customization-call',
        rawServerName: 'posthog',
        rawToolName: 'exec',
        input: { command: `call ui-customization-set ${JSON.stringify({ context, layout: custom.layout })}` },
        status: phase === 'completed' ? 'completed' : 'in_progress',
        contentBlocks: [],
    }
    return {
        streamKey: 'customization-run',
        toolCallId: invocation.toolCallId,
        toolName: resolveToolCall(invocation).resolvedKey,
        rawToolName: invocation.rawToolName,
        phase,
        invocation,
        source: 'live',
    }
}

async function mounted(props: SidebarCustomizationProps): Promise<ReturnType<typeof sidebarCustomizationLogic>> {
    const logic = sidebarCustomizationLogic(props)
    logic.mount()
    await expectLogic(logic).toFinishAllListeners()
    return logic
}

describe('sidebarCustomizationLogic', () => {
    beforeEach(() => {
        localStorage.clear()
        initKeaTests()
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.UI_CUSTOMIZATION]: true })
    })
    afterEach(() => {
        cleanup()
        jest.restoreAllMocks()
    })

    it.each(['load', 'reset', 'restore'] as const)(
        'reconciles %s across pane unmount and remount without an extra stale read',
        async (operation) => {
            const props = configuration()
            const logic = sidebarCustomizationLogic(props)
            const leave = logic.mount()
            await expectLogic(logic).toFinishAllListeners()
            const pending = deferred<CustomizationApi>()
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
            const pending = deferred<CustomizationApi>()
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

    it('keeps persisted layouts separate for contexts sharing a user, project, and storage key', async () => {
        const first = configuration()
        const second = configuration()
        second.configuration.context = 'other_sidebar'
        second.configuration.retrieve = jest.fn().mockResolvedValue(defaults)
        const firstLogic = sidebarCustomizationLogic(first)
        const secondLogic = sidebarCustomizationLogic(second)
        const leaveFirst = firstLogic.mount()
        const leaveSecond = secondLogic.mount()
        await expectLogic(firstLogic).toFinishAllListeners()
        await expectLogic(secondLogic).toFinishAllListeners()
        leaveFirst()
        leaveSecond()

        const firstRead = deferred<CustomizationApi>()
        const secondRead = deferred<CustomizationApi>()
        jest.spyOn(first.configuration, 'retrieve').mockReturnValueOnce(firstRead.promise)
        jest.spyOn(second.configuration, 'retrieve').mockReturnValueOnce(secondRead.promise)
        const remountedFirst = sidebarCustomizationLogic(first)
        const remountedSecond = sidebarCustomizationLogic(second)
        const releaseFirst = remountedFirst.mount()
        const releaseSecond = remountedSecond.mount()
        expect(remountedFirst.values.shownSidebar).toEqual(custom)
        expect(remountedSecond.values.shownSidebar).toEqual(defaults)
        firstRead.resolve(custom)
        secondRead.resolve(defaults)
        await expectLogic(remountedFirst).toFinishAllListeners()
        await expectLogic(remountedSecond).toFinishAllListeners()
        releaseFirst()
        releaseSecond()
    })

    it('recovers a failed reset after remount and releases its retained mount', async () => {
        const props = configuration()
        const logic = sidebarCustomizationLogic(props)
        const leave = logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        const pending = deferred<CustomizationApi>()
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

    it('ignores a cached custom layout and makes no requests while customization is disabled', async () => {
        featureFlagLogic.actions.setFeatureFlags([], {})
        const props = configuration()
        const logic = await mounted(props)
        logic.actions.requestSidebarSuccess(custom)
        await logic.asyncActions.loadSidebar()
        await logic.asyncActions.resetSidebar(custom.layout)
        await logic.asyncActions.restoreSidebar(custom.layout)

        expect(logic.values.savedSidebar).toEqual(custom)
        expect(logic.values.shownSidebar).toEqual(defaults)
        expect(props.configuration.retrieve).not.toHaveBeenCalled()
        expect(props.configuration.reset).not.toHaveBeenCalled()
        expect(props.configuration.restore).not.toHaveBeenCalled()
    })

    it('loads customization when feature flags arrive after mount', async () => {
        featureFlagLogic.actions.setFeatureFlags([], {})
        const logic = await mounted(configuration())
        expect(logic.values.shownSidebar).toEqual(defaults)

        await expectLogic(logic, () => {
            featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.UI_CUSTOMIZATION]: true })
        }).toDispatchActions(['requestSidebarSuccess'])
        expect(logic.values.shownSidebar).toEqual(custom)
    })

    it.each([false, true])(
        'discards an in-flight response after disabling customization, failure=%s',
        async (fails) => {
            const props = configuration()
            const logic = await mounted(props)
            const read = deferred<CustomizationApi>()
            jest.spyOn(props.configuration, 'retrieve').mockReturnValueOnce(read.promise)
            const reading = logic.asyncActions.loadSidebar()
            featureFlagLogic.actions.setFeatureFlags([], {})
            fails ? read.reject(new Error('Old request failed')) : read.resolve(defaults)
            await reading

            expect(logic.values.savedSidebar).toEqual(custom)
            expect(logic.values.shownSidebar).toEqual(defaults)
            expect(logic.values.sidebarFailed).toBe(false)
        }
    )

    it('skips queued writes while disabled and shows the server layout after re-enabling', async () => {
        const props = configuration()
        const logic = await mounted(props)
        const reset = deferred<CustomizationApi>()
        jest.spyOn(props.configuration, 'reset').mockReturnValueOnce(reset.promise)
        const success = jest.spyOn(toast, 'success')
        const resetting = logic.asyncActions.resetSidebar(custom.layout)
        await Promise.resolve()
        const restoring = logic.asyncActions.restoreSidebar(custom.layout)
        featureFlagLogic.actions.setFeatureFlags([], {})
        reset.resolve(defaults)
        await Promise.all([resetting, restoring])

        await expectLogic(logic, () => {
            featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.UI_CUSTOMIZATION]: true })
        }).toDispatchActions(['requestSidebarSuccess'])
        await expectLogic(logic).toFinishAllListeners()

        expect(props.configuration.restore).not.toHaveBeenCalled()
        expect(success).not.toHaveBeenCalled()
        expect(logic.values.shownSidebar).toEqual(custom)
        expect(logic.values.sidebarLoading).toBe(false)
    })

    it.each([false, true])('shows the default while the first request is pending, failure=%s', async (fails) => {
        const props = configuration()
        const read = deferred<CustomizationApi>()
        jest.spyOn(props.configuration, 'retrieve').mockReturnValueOnce(read.promise)
        const logic = sidebarCustomizationLogic(props)
        logic.mount()

        expect(logic.values.sidebarLayout).toEqual(defaults.layout)
        expect(logic.values.sidebarCustomized).toBe(false)

        fails ? read.reject(new Error('Unavailable')) : read.resolve(custom)
        await expectLogic(logic).toDispatchActions([fails ? 'requestSidebarFailure' : 'requestSidebarSuccess'])
        expect(logic.values.sidebarFailed).toBe(fails)
        expect(logic.values.sidebarLayout).toEqual(fails ? defaults.layout : custom.layout)
        expect(logic.values.sidebarCustomized).toBe(!fails)
    })

    it.each([
        ['reset', false],
        ['reset', true],
        ['restore', false],
        ['restore', true],
    ] as const)('keeps %s and its cache when an older GET finishes, failure=%s', async (operation, fails) => {
        const props = configuration()
        const logic = await mounted(props)
        const expected = operation === 'reset' ? defaults : custom
        const stale = operation === 'reset' ? custom : defaults
        const read = deferred<CustomizationApi>()
        jest.spyOn(props.configuration, 'retrieve').mockReturnValueOnce(read.promise)
        const reading = logic.asyncActions.loadSidebar()

        await (operation === 'reset'
            ? logic.asyncActions.resetSidebar(custom.layout)
            : logic.asyncActions.restoreSidebar(custom.layout))
        expect(logic.values.savedSidebar).toEqual(expected)

        fails ? read.reject(new Error('Old request failed')) : read.resolve(stale)
        await reading
        expect(logic.values.shownSidebar).toEqual(expected)
        expect(logic.values.savedSidebar).toEqual(expected)
        expect(logic.values.sidebarFailed).toBe(false)
        expect(logic.values.sidebarLoading).toBe(false)
    })

    it.each(['reset', 'restore'] as const)('waits for %s before reloading during the write', async (operation) => {
        const props = configuration()
        const logic = await mounted(props)
        const expected = operation === 'reset' ? defaults : custom
        const write = deferred<CustomizationApi>()
        const successToast = jest.spyOn(toast, 'success')
        const read = jest.spyOn(props.configuration, 'retrieve').mockClear().mockResolvedValue(expected)
        const writer = jest.spyOn(props.configuration, operation).mockReturnValueOnce(write.promise)
        const writing =
            operation === 'reset'
                ? logic.asyncActions.resetSidebar(custom.layout)
                : logic.asyncActions.restoreSidebar(custom.layout)
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
        expect(logic.values.sidebarLoading).toBe(false)
        if (operation === 'reset') {
            expect(successToast).toHaveBeenCalledWith(
                expect.objectContaining({ title: 'Sidebar reset to the default' })
            )
        }
    })

    it.each([false, true])('finishes queued writes in order after an older reset, failure=%s', async (fails) => {
        const props = configuration()
        const logic = await mounted(props)
        const reset = deferred<CustomizationApi>()
        jest.spyOn(props.configuration, 'reset').mockReturnValueOnce(reset.promise)
        const errorToast = jest.spyOn(toast, 'error')
        const resetting = logic.asyncActions.resetSidebar(custom.layout)
        const restoring = logic.asyncActions.restoreSidebar(custom.layout)
        logic.actions.loadSidebar()
        expect(props.configuration.restore).not.toHaveBeenCalled()

        fails ? reset.reject(new Error('Old reset failed')) : reset.resolve(defaults)
        await Promise.all([resetting, restoring])
        await expectLogic(logic).toFinishAllListeners()
        expect(props.configuration.restore).toHaveBeenCalledTimes(1)
        expect(logic.values.shownSidebar).toEqual(custom)
        expect(logic.values.sidebarFailed).toBe(false)
        expect(logic.values.sidebarLoading).toBe(false)
        expect(errorToast).not.toHaveBeenCalled()
    })

    it.each(['reset', 'restore'] as const)('reloads server state after the current %s fails', async (operation) => {
        const props = configuration()
        const logic = await mounted(props)
        jest.spyOn(props.configuration, operation).mockRejectedValueOnce(new Error('Current write failed'))
        const read = jest.spyOn(props.configuration, 'retrieve').mockClear()
        const errorToast = jest.spyOn(toast, 'error')
        await (operation === 'reset'
            ? logic.asyncActions.resetSidebar(custom.layout)
            : logic.asyncActions.restoreSidebar(custom.layout))
        await expectLogic(logic).toFinishAllListeners()

        expect(read).toHaveBeenCalledTimes(1)
        expect(errorToast).toHaveBeenCalled()
        expect(logic.values.shownSidebar).toEqual(custom)
        expect(logic.values.sidebarFailed).toBe(false)
        expect(logic.values.sidebarLoading).toBe(false)
    })

    it.each(['load', 'reset'] as const)('gives up on a stalled %s when its request times out', async (operation) => {
        const props = configuration()
        const logic = await mounted(props)
        const timeout = new AbortController()
        jest.spyOn(AbortSignal, 'timeout').mockReturnValue(timeout.signal)
        const method = operation === 'load' ? 'retrieve' : 'reset'
        jest.spyOn(props.configuration, method).mockImplementationOnce(
            (_projectId: string, signal: AbortSignal) =>
                new Promise<CustomizationApi>((_, reject) => {
                    // Like fetch, an already-aborted signal rejects at once.
                    if (signal.aborted) {
                        reject(signal.reason)
                    }
                    signal.addEventListener('abort', () => reject(signal.reason))
                })
        )
        const read = jest.spyOn(props.configuration, 'retrieve')
        read.mockClear()
        const request =
            operation === 'load' ? logic.asyncActions.loadSidebar() : logic.asyncActions.resetSidebar(custom.layout)
        expect(logic.values.sidebarLoading).toBe(true)

        timeout.abort(new DOMException('The request timed out.', 'TimeoutError'))
        await request
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.sidebarLoading).toBe(false)
        expect(logic.values.sidebarFailed).toBe(operation === 'load')
        expect(read).toHaveBeenCalledTimes(1)
    })

    it.each([false, true])('restores the saved layout through Undo, left pane=%s', async (leftPane) => {
        const props = configuration()
        const successToast = jest.spyOn(toast, 'success')
        let logic = await mounted(props)
        expect(logic.values.shownSidebar).toEqual(custom)

        await logic.asyncActions.resetSidebar(custom.layout)
        expect(logic.values.shownSidebar).toEqual(defaults)
        const undo = successToast.mock.calls.find(([options]) => options.title === 'Sidebar reset to the default')?.[0]
            .action
        expect(undo?.label).toBe('Undo')
        if (leftPane) {
            logic.unmount()
        }
        await undo?.onClick()
        expect(props.configuration.restore).toHaveBeenCalledWith(
            props.projectId,
            custom.layout,
            expect.any(AbortSignal)
        )
        expect(logic.isMounted()).toBe(!leftPane)
        if (leftPane) {
            logic = await mounted(props)
        }
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.shownSidebar).toEqual(custom)
    })

    it.each(['focus', 'visibilitychange', 'navigation'] as const)(
        'reloads on %s only once the last load is 30 seconds old',
        async (trigger) => {
            let now = 1_000_000
            jest.spyOn(Date, 'now').mockImplementation(() => now)
            const props = configuration()
            const logic = await mounted(props)
            const comeBack = async (): Promise<void> => {
                if (trigger === 'focus') {
                    window.dispatchEvent(new Event('focus'))
                } else if (trigger === 'visibilitychange') {
                    document.dispatchEvent(new Event('visibilitychange'))
                } else {
                    router.actions.push(`/analytics/${now}`)
                }
                await expectLogic(logic).toFinishAllListeners()
            }

            now += 29_999
            await comeBack()
            expect(props.configuration.retrieve).toHaveBeenCalledTimes(1)

            now += 1
            await comeBack()
            expect(props.configuration.retrieve).toHaveBeenCalledTimes(2)
        }
    )

    it.each([
        ['a completed save to this context', 'completed', 'analytics_sidebar', 2],
        ['a save that has only started', 'started', 'analytics_sidebar', 1],
        ['a completed save to another context', 'completed', 'other_sidebar', 1],
    ] as const)('reloads after PostHog AI makes %s through exec', async (_name, phase, context, reads) => {
        const props = configuration()
        await mounted(props)
        renderHook(() => SidebarAgentListener(props))

        act(() => toolStreamEventsLogic.actions.emitToolEvent(execEvent(phase, context)))
        await expectLogic(sidebarCustomizationLogic(props)).toFinishAllListeners()

        expect(props.configuration.retrieve).toHaveBeenCalledTimes(reads)
    })
})
