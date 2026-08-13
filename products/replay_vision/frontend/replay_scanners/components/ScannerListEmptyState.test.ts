import { type ScannerListEmptyStateVariant, scannerListEmptyStateVariant } from './ScannerListEmptyState'

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
})
