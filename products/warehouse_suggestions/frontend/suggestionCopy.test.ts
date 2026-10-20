import type { WarehouseSuggestionMaterializePayloadApi } from './generated/api.schemas'
import { UNKNOWN_SOURCES_CAVEAT, dataAgeLabel, todayAgeLabel } from './suggestionCopy'

const DAY = 24 * 60 * 60
const HOUR = 60 * 60

function payload(
    freshnessTodaySeconds: number | null,
    unknownSources: WarehouseSuggestionMaterializePayloadApi['unknown_sources'] = { names: [], hidden_count: 0 }
): WarehouseSuggestionMaterializePayloadApi {
    return {
        subject_name: 'orders',
        refresh_interval_seconds: DAY,
        saves_seconds_per_month: 1200,
        saves_bytes_per_month: 0,
        freshness_today_seconds: freshnessTodaySeconds,
        freshness_after_seconds: DAY + (freshnessTodaySeconds ?? 0),
        live_sources: { names: [], hidden_count: 0 },
        unknown_sources: unknownSources,
    }
}

describe('suggestionCopy', () => {
    it.each<[string, WarehouseSuggestionMaterializePayloadApi, string, string | null, string]>([
        ['known sources', payload(HOUR), 'Data up to 1 day and 1 hour old', null, 'Today: up to 1 hour old'],
        ['live sources', payload(null), 'Data up to 1 day old', null, 'Today: live'],
        [
            'a source the caller cannot see has no schedule',
            payload(null, { names: [], hidden_count: 1 }),
            'Adds up to 1 day to source age',
            UNKNOWN_SOURCES_CAVEAT,
            'Today: unknown for some sources',
        ],
    ])('states the data age honestly when %s', (_name, input, label, caveat, today) => {
        expect(dataAgeLabel(input, DAY)).toEqual({ label, caveat })
        expect(todayAgeLabel(input)).toEqual(today)
    })
})
