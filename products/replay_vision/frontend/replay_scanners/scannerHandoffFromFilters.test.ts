import { defaultRecordingDurationFilter } from 'scenes/session-recordings/playlist/sessionRecordingsPlaylistLogic'

import {
    FilterLogicalOperator,
    PropertyFilterType,
    PropertyOperator,
    RecordingDurationFilter,
    RecordingUniversalFilters,
    UniversalFiltersGroupValue,
} from '~/types'

import { scannerHandoffFromFilters } from './scannerHandoffFromFilters'

/** A default replay filter set, with `values` filling the inner filter group the converter reads. */
function filters(
    partial: Partial<RecordingUniversalFilters> & { values?: UniversalFiltersGroupValue[] } = {}
): RecordingUniversalFilters {
    const { values = [], ...rest } = partial
    return {
        filter_test_accounts: false,
        date_from: '-3d',
        date_to: null,
        duration: [defaultRecordingDurationFilter],
        order: 'start_time',
        order_direction: 'DESC',
        filter_group: {
            type: FilterLogicalOperator.And,
            values: [{ type: FilterLogicalOperator.And, values }],
        },
        ...rest,
    } as RecordingUniversalFilters
}

const PAGEVIEW = { id: '$pageview', type: 'events' } as unknown as UniversalFiltersGroupValue
const LONG_SESSIONS: RecordingDurationFilter = {
    type: PropertyFilterType.Recording,
    key: 'active_seconds',
    value: 600,
    operator: PropertyOperator.GreaterThan,
}

function handoffQuery(f: RecordingUniversalFilters): Record<string, any> {
    return JSON.parse(scannerHandoffFromFilters(f).searchParams.filters)
}

describe('scannerHandoffFromFilters', () => {
    // A scanner carrying session IDs is pinned to recordings that already exist, so it matches
    // nothing ever while still looking healthy in the scanner list.
    it('drops pinned session IDs from the query', () => {
        const query = handoffQuery(filters({ values: [PAGEVIEW], session_ids: ['abc-123'] }))

        expect(query.session_ids).toBeUndefined()
        expect(query.events).toHaveLength(1)
    })

    // The API rejects exposure inside `query`, so leaving it there opens a wizard that can't be
    // saved. It has to travel as the experiment deep link the wizard access-checks instead.
    it('sends experiment exposure as targeting params, never inside the query', () => {
        const { searchParams } = scannerHandoffFromFilters(
            filters({ values: [PAGEVIEW], experiment_exposure: { experiment_id: 42, variant: 'test' } })
        )

        expect(searchParams).toMatchObject({ experiment: '42', variant: 'test' })
        expect(JSON.parse(searchParams.filters)).not.toHaveProperty('experiment_exposure')
    })

    it('omits the variant param when the filters cover every variant', () => {
        const { searchParams } = scannerHandoffFromFilters(
            filters({ values: [PAGEVIEW], experiment_exposure: { experiment_id: 42 } })
        )

        expect(searchParams.experiment).toEqual('42')
        expect(searchParams).not.toHaveProperty('variant')
    })

    describe('narrowsSessions', () => {
        // Guards the one-click path to a scanner pointed at every session: the replay list counts
        // these as filters, but a scanner keeps none of them.
        it.each([
            ['an untouched filter set', filters()],
            ['only a date range', filters({ date_from: '-7d' })],
            ['only pinned session IDs', filters({ session_ids: ['abc-123'] })],
            ['only the default duration floor', filters({ duration: [defaultRecordingDurationFilter] })],
        ])('is false for %s', (_label, f) => {
            expect(scannerHandoffFromFilters(f).narrowsSessions).toBe(false)
        })

        it.each([
            ['an event filter', filters({ values: [PAGEVIEW] })],
            ['a duration the user moved off the default', filters({ duration: [LONG_SESSIONS] })],
            ['experiment exposure', filters({ experiment_exposure: { experiment_id: 42 } })],
        ])('is true for %s', (_label, f) => {
            expect(scannerHandoffFromFilters(f).narrowsSessions).toBe(true)
        })
    })
})
