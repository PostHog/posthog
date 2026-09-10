import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'
import { sessionPlayerModalLogic } from 'scenes/session-recordings/player/modal/sessionPlayerModalLogic'

import { initKeaTests } from '~/test/init'

import { getBackgroundStepBlockReason, getPageStepBlockReason, heatmapCreationLogic } from './heatmapCreationLogic'

describe('heatmapCreationLogic', () => {
    beforeEach(() => {
        initKeaTests()
        jest.spyOn(api, 'queryHogQL').mockResolvedValue({ results: [] } as any)
    })

    afterEach(() => {
        jest.restoreAllMocks()
    })

    it.each([
        ['missing page URL', null, true, null, true, 'Enter a page URL to continue'],
        ['invalid page URL', 'example.com', false, null, true, 'Enter a valid page URL to continue'],
        [
            'invalid data URL',
            'https://example.com',
            true,
            'example.com/*',
            false,
            'Enter a valid heatmap data URL to continue',
        ],
        ['valid exact URLs', 'https://example.com', true, 'https://example.com/pricing', true, null],
        ['valid pattern data URL', 'https://example.com', true, 'https://example.com/*', true, null],
    ])(
        'applies structural page validation for %s',
        (_case, displayUrl, isDisplayUrlValid, dataUrl, isDataUrlValid, expected) => {
            expect(getPageStepBlockReason({ displayUrl, isDisplayUrlValid, dataUrl, isDataUrlValid })).toBe(expected)
        }
    )

    it.each([
        ['Screenshot without authorization', 'public', 'screenshot', false, false, null],
        [
            'Iframe without authorization',
            'public',
            'iframe',
            false,
            false,
            'Authorize this URL or choose Screenshot to continue',
        ],
        ['authorized Iframe', 'public', 'iframe', true, false, null],
        [
            'login-required page without a recording',
            'login',
            'screenshot',
            true,
            false,
            'Choose a session recording moment to continue',
        ],
        ['login-required page with a recording', 'login', 'screenshot', true, true, null],
    ] as const)(
        'applies background validation for %s',
        (_case, pageAccess, type, isAuthorized, hasRecordingBackground, expected) => {
            expect(
                getBackgroundStepBlockReason({
                    pageAccess,
                    type,
                    isDisplayUrlAuthorized: isAuthorized,
                    hasRecordingBackground,
                })
            ).toBe(expected)
        }
    )

    it('allows creation when the readiness check returns zero matching interactions', async () => {
        const logic = heatmapCreationLogic
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.setDisplayUrl('https://example.com/pricing')
        logic.actions.requestPageDataCheck('manual')

        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.hasMatchingData).toBe(false)
        expect(logic.values.pageStepBlockReason).toBeNull()
    })

    it('keeps a selected recording background in the wizard through the interactive heatmap', async () => {
        const logic = heatmapCreationLogic
        logic.mount()
        const modalLogic = sessionPlayerModalLogic.findMounted()
        expect(modalLogic).toBeTruthy()
        logic.actions.setDisplayUrl('https://example.com/pricing')
        logic.actions.setPageAccess('login')
        const storageKey = 'recording-background'
        localStorage.setItem(
            storageKey,
            JSON.stringify({
                html: '<html><body>Pricing</body></html>',
                width: 1280,
                height: 720,
                url: 'https://example.com/pricing',
            })
        )

        modalLogic?.actions.openSessionPlayer({ id: 'recording-one' }, null, {
            type: 'heatmap-background-selection',
            targetUrl: 'https://example.com/pricing',
            matchingRecordingCount: 2,
        })
        expect(logic.values.terminalOutcome).toBeNull()

        modalLogic?.actions.completeHeatmapBackgroundSelection(storageKey)
        await expectLogic(logic).toFinishAllListeners()
        const startingPathname = router.values.location.pathname

        expect(logic.values.currentStep).toBe('review')
        expect(logic.values.recordingBackground).toEqual({ storageKey, matchingRecordingCount: 2 })
        expect(logic.values.recordingBackgroundData?.html).toContain('Pricing')
        expect(logic.values.terminalOutcome).toBeNull()

        logic.actions.openRecordingHeatmap()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.recordingHeatmapOpen).toBe(true)
        expect(logic.values.terminalOutcome).toBeNull()
        expect(router.values.location.pathname).toBe(startingPathname)

        logic.actions.closeRecordingHeatmap()
        expect(logic.values.recordingHeatmapOpen).toBe(false)
        expect(logic.values.recordingBackgroundData?.html).toContain('Pricing')

        logic.actions.openRecordingHeatmap()
        logic.actions.finishRecordingHeatmap()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.terminalOutcome).toBe('recording_handoff')
        expect(router.values.location.pathname).toContain('/heatmaps')
        expect(router.values.location.pathname).not.toContain('/heatmaps/new')
    })

    it('discards a readiness result after the effective data URL changes', async () => {
        let resolveFirstCheck: ((value: { results: number[][] }) => void) | undefined
        let markFirstCheckStarted: (() => void) | undefined
        const firstCheck = new Promise<{ results: number[][] }>((resolve) => {
            resolveFirstCheck = resolve
        })
        const firstCheckStarted = new Promise<void>((resolve) => {
            markFirstCheckStarted = resolve
        })
        const queryMock = jest.mocked(api.queryHogQL)
        const logic = heatmapCreationLogic
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        queryMock.mockClear()
        queryMock.mockImplementationOnce(() => {
            markFirstCheckStarted?.()
            return firstCheck as ReturnType<typeof api.queryHogQL>
        })
        queryMock.mockResolvedValueOnce({ results: [[0]] } as any)

        logic.actions.setDisplayUrl('https://example.com/first')
        logic.actions.requestPageDataCheck('manual')
        await firstCheckStarted

        await expectLogic(logic, () => {
            logic.actions.setDisplayUrl('https://example.com/second')
            logic.actions.requestPageDataCheck('manual')
        }).toDispatchActions(['checkPageDataSuccess'])

        resolveFirstCheck?.({ results: [[12]] })
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.currentPageDataCheck).toEqual(
            expect.objectContaining({
                url: 'https://example.com/second',
                outcome: 'none',
            })
        )
        expect(logic.values.hasMatchingData).toBe(false)
    })

    it('clears an in-flight readiness check when the URL becomes invalid', async () => {
        let resolveCheck: ((value: { results: number[][] }) => void) | undefined
        let markCheckStarted: (() => void) | undefined
        const pendingCheck = new Promise<{ results: number[][] }>((resolve) => {
            resolveCheck = resolve
        })
        const checkStarted = new Promise<void>((resolve) => {
            markCheckStarted = resolve
        })
        const logic = heatmapCreationLogic
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        jest.mocked(api.queryHogQL).mockImplementationOnce(() => {
            markCheckStarted?.()
            return pendingCheck as ReturnType<typeof api.queryHogQL>
        })

        logic.actions.setDisplayUrl('https://example.com/pricing')
        logic.actions.requestPageDataCheck('manual')
        await checkStarted

        logic.actions.setDisplayUrl('not a URL')
        await expectLogic(logic).toDispatchActions(['checkPageDataSuccess'])

        expect(logic.values.currentPageDataCheck).toBeNull()
        expect(logic.values.pageDataCheckLoading).toBe(false)

        resolveCheck?.({ results: [[12]] })
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.currentPageDataCheck).toBeNull()
    })
})
