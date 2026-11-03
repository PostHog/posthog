import { expectLogic } from 'kea-test-utils'

import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { sessionRecordingSavedFiltersLogic } from 'scenes/session-recordings/filters/sessionRecordingSavedFiltersLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { FilterLogicalOperator, PropertyFilterType, SessionRecordingPlaylistType } from '~/types'

import { replayScannerLogic } from './replayScannerLogic'
import { scannerSavedFilterLogic } from './scannerSavedFilterLogic'

function savedFilter(overrides: Record<string, unknown> = {}): SessionRecordingPlaylistType {
    return {
        short_id: 'savedFilter1',
        name: 'Checkout visits',
        type: 'filters',
        filters: {
            date_from: '-3d',
            date_to: null,
            filter_test_accounts: true,
            recommended_only: true,
            event_match_scope: 'recording',
            session_ids: ['pinned-session'],
            duration: [{ type: PropertyFilterType.Recording, key: 'active_seconds', value: 5, operator: 'gt' }],
            filter_group: {
                type: FilterLogicalOperator.And,
                values: [
                    {
                        type: FilterLogicalOperator.And,
                        values: [{ id: '$pageview', name: '$pageview', type: 'events' }],
                    },
                ],
            },
            ...overrides,
        },
    } as unknown as SessionRecordingPlaylistType
}

describe('scannerSavedFilterLogic', () => {
    let scannerLogic: ReturnType<typeof replayScannerLogic.build>
    let logic: ReturnType<typeof scannerSavedFilterLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team/vision/scanners/:id/': () => [404, {}],
            },
        })
        localStorage.clear()
        sessionStorage.clear()
        initKeaTests()
        jest.spyOn(lemonToast, 'success').mockImplementation()
        jest.spyOn(lemonToast, 'warning').mockImplementation()
        scannerLogic = replayScannerLogic({ id: 'new' })
        scannerLogic.mount()
        logic = scannerSavedFilterLogic({ scannerId: 'new' })
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
        scannerLogic.unmount()
        jest.restoreAllMocks()
    })

    it.each([
        ['with a duration', {}],
        ['without a duration', { duration: undefined }],
    ])('copies a saved filter %s into the scanner query and clears the pending pick', async (_, overrides) => {
        await expectLogic(logic, () => {
            sessionRecordingSavedFiltersLogic.actions.requestApplySavedFilter(savedFilter(overrides))
        }).toFinishAllListeners()

        const query = scannerLogic.values.scanner.query
        expect(query?.events).toEqual([expect.objectContaining({ id: '$pageview' })])
        expect(query?.filter_test_accounts).toBe(true)
        expect(query?.recommended_only).toBe(true)
        expect(query?.event_match_scope).toBe('recording')
        expect(query?.session_ids).toBeUndefined()
        expect(query?.date_from).toBeUndefined()
        expect(sessionRecordingSavedFiltersLogic.values.pendingFilterApplication).toBeNull()
    })

    it('refuses a saved filter that targets an experiment', async () => {
        const before = scannerLogic.values.scanner.query

        await expectLogic(logic, () => {
            sessionRecordingSavedFiltersLogic.actions.requestApplySavedFilter(
                savedFilter({ experiment_exposure: { experiment_id: 7, variant: null } })
            )
        }).toFinishAllListeners()

        expect(scannerLogic.values.scanner.query).toEqual(before)
        expect(lemonToast.warning).toHaveBeenCalled()
    })
})
