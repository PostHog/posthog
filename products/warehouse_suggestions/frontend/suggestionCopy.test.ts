import type { WarehouseSuggestionMaterializePayloadApi } from './generated/api.schemas'
import {
    MonthlySaving,
    SavingHighlight,
    MainSavingKind,
    UNKNOWN_SOURCES_CAVEAT,
    dataAgeLabel,
    materializeHighlight,
    notNowCondition,
    savingHighlight,
    savingSentence,
    suggestedScheduleHint,
    summarySavings,
    todayAgeLabel,
} from './suggestionCopy'

const DAY = 24 * 60 * 60
const HOUR = 60 * 60
const MB = 1024 ** 2
const TB = 1024 ** 4

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
        refresh_mode: 'full',
        refresh_interval_basis: 'savings',
        main_saving: null,
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

    it.each<[string, MonthlySaving, SavingHighlight, string]>([
        [
            'time and bytes',
            { seconds: 17 * 60, bytes: 3.2 * TB },
            {
                amount: '~17 minutes',
                detail: '~3.20 TB less scanned',
                narrowLabel: 'saved a month, ~3.20 TB less scanned',
            },
            'Saves about 17 minutes of query time and 3.20 TB of scanning a month',
        ],
        [
            'time and too few bytes to name',
            { seconds: 17 * 60, bytes: 40 * MB },
            { amount: '~17 minutes', detail: null, narrowLabel: 'saved a month' },
            'Saves about 17 minutes of query time a month',
        ],
        [
            'only bytes',
            { seconds: 30, bytes: 40 * MB },
            { amount: '~40.00 MB', detail: 'less scanned', narrowLabel: 'less scanned a month' },
            'Saves about 40.00 MB of scanning a month',
        ],
    ])('names every saving worth naming when a suggestion saves %s', (_name, saving, highlight, sentence) => {
        expect(savingHighlight(saving)).toEqual(highlight)
        expect(savingSentence(saving)).toEqual(sentence)
    })

    it.each<[string, MainSavingKind | null, number, number, SavingHighlight]>([
        [
            'saves waiting but its refreshes cost background work',
            'waiting',
            2 * HOUR,
            -HOUR,
            {
                amount: '~2 hours',
                detail: 'less waiting',
                narrowLabel: 'less waiting a month',
                tooltip: ['Refreshing costs ~1 hour of background work a month', '~3.20 TB less scanned a month'],
            },
        ],
        [
            'saves little waiting but a lot of scanning',
            'scanned',
            10 * 60,
            0,
            {
                amount: '~3.20 TB',
                detail: 'less scanned',
                narrowLabel: 'less scanned a month',
                tooltip: ['~10 minutes less waiting a month'],
            },
        ],
        [
            'saves only background work',
            'background',
            0,
            9 * HOUR,
            {
                amount: '~9 hours',
                detail: 'less background work',
                narrowLabel: 'less background work a month',
                tooltip: ['~3.20 TB less scanned a month'],
            },
        ],
        [
            'was made before the main saving was recorded',
            null,
            0,
            0,
            {
                amount: '~20 minutes',
                detail: '~3.20 TB less scanned',
                narrowLabel: 'saved a month, ~3.20 TB less scanned',
            },
        ],
    ])(
        'leads with the saving that earned a materialize suggestion that %s',
        (_name, main, waiting, background, highlight) => {
            const input = {
                ...payload(null),
                saves_bytes_per_month: 3.2 * TB,
                waiting_seconds_saved_per_month: waiting,
                background_seconds_saved_per_month: background,
                main_saving: main,
            }

            expect(materializeHighlight(input)).toEqual(highlight)
        }
    )

    it('leads the summary with waiting and lists the other savings without adding them up', () => {
        expect(
            summarySavings({ views: 2, saving: { seconds: 11 * HOUR, bytes: 3.2 * TB }, waitingSeconds: 2 * HOUR })
        ).toEqual({
            waiting: '~2 hours',
            headline: null,
            detail: 'Also ~9 hours less background work and ~3.20 TB less scanned, across 2 views',
        })
    })

    it.each<[Parameters<typeof suggestedScheduleHint>[0], string]>([
        ['source_sync', "sources don't sync more often"],
        ['read_rate', "People don't read it more often"],
        ['consumer_refresh', "The views that read it don't refresh more often"],
        ['fastest_schedule', 'the most often PostHog refreshes a view'],
        ['savings', 'saves more than it costs'],
        [null, 'saves more than it costs'],
    ])('explains a %s interval with its own reason', (basis, reason) => {
        expect(suggestedScheduleHint(basis, '1 day')).toContain(reason)
    })

    it.each([
        ['certify', 'reads grow'],
        ['deprecate', 'refreshes cost'],
        ['materialize', 'save a lot more'],
        ['unmaterialize', 'save a lot more'],
    ])('says what has to grow before a not-now %s suggestion returns', (kind, condition) => {
        expect(notNowCondition(kind)).toContain(condition)
    })
})
