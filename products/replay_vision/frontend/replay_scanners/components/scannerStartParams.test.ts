import { scannerStartSearchParams } from './scannerStartParams'

describe('scannerStartSearchParams', () => {
    // A card starts the flow with whatever query string the previous step left behind, so carrying
    // the whole thing lets a `template` key outlive its template: downstream readers take it as the
    // source of the config, locking the type selector and captioning the categories as the
    // template's. The editor only strips the key once, on first load, so the picker has to.
    it.each<[string, Record<string, unknown>, string | null, Record<string, unknown>]>([
        ['blank card drops a stale template key', { template: 'dead_end' }, null, {}],
        [
            'template card replaces a stale template key',
            { template: 'dead_end' },
            'user_intent',
            { template: 'user_intent' },
        ],
        ['blank card keeps unrelated params', { template: 'dead_end', experiment: '7' }, null, { experiment: '7' }],
        [
            'template card keeps unrelated params',
            { experiment: '7' },
            'user_intent',
            { experiment: '7', template: 'user_intent' },
        ],
    ])('%s', (_name, searchParams, templateKey, expected) => {
        expect(scannerStartSearchParams(searchParams, templateKey)).toEqual(expected)
    })
})
