import {
    type ScannerListEmptyStateVariant,
    computeScannerListEmptyStateVariant,
    scannerListEmptyStateVariant,
} from './ScannerListEmptyState'

describe('scannerListEmptyStateVariant', () => {
    // The flag can serve values this build doesn't know (a new arm added before the frontend
    // deploys, control, or a plain boolean); all of them must degrade to the control empty state,
    // or the control arm gets contaminated.
    it.each<[unknown, ScannerListEmptyStateVariant | null]>([
        ['templates', 'templates'],
        ['example-observations', 'example-observations'],
        ['control', null],
        ['some-future-arm', null],
        [true, null],
        [false, null],
        [undefined, null],
    ])('narrows flag value %p to variant %p', (flagValue, expected) => {
        expect(scannerListEmptyStateVariant(flagValue)).toBe(expected)
    })

    // Reading the flag is what reports exposure, so any guarded-out render must return null
    // WITHOUT touching the flags object; a read here logs users who never saw the empty state.
    describe('computeScannerListEmptyStateVariant', () => {
        const eligible = {
            onScannersTab: true,
            receivedFeatureFlags: true,
            scannerStatsLoading: false,
            scannerTotal: 0,
        }
        const flagsServing = (value: unknown): Record<string, unknown> => ({
            'replay-vision-empty-state-experiment': value,
        })

        it('returns the variant when the empty state actually shows', () => {
            expect(computeScannerListEmptyStateVariant({ ...eligible, featureFlags: flagsServing('templates') })).toBe(
                'templates'
            )
        })

        it.each<[string, Partial<typeof eligible>]>([
            ['on the usage tab', { onScannersTab: false }],
            ['before flags load', { receivedFeatureFlags: false }],
            ['while stats load', { scannerStatsLoading: true }],
            ['with stats missing', { scannerTotal: undefined }],
            ['with existing scanners', { scannerTotal: 3 }],
        ])('returns null without reading the flag %s', (_label, overrides) => {
            const flagReads: string[] = []
            const trackedFlags = new Proxy(
                {},
                {
                    get: (_target, prop) => {
                        flagReads.push(String(prop))
                        return 'templates'
                    },
                }
            )
            expect(
                computeScannerListEmptyStateVariant({ ...eligible, ...overrides, featureFlags: trackedFlags })
            ).toBeNull()
            expect(flagReads).toEqual([])
        })
    })
})
