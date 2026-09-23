import type { HogFlowConversionApi } from 'products/workflows/frontend/generated/api.schemas'

import { DEFAULT_BROADCAST_CONVERSION, formatConversionWindow } from './broadcastWizardLogic'

const conversion = (fields: Partial<HogFlowConversionApi>): HogFlowConversionApi =>
    ({ events: [], filters: [], ...fields }) as HogFlowConversionApi

describe('formatConversionWindow', () => {
    it('reads the duration a new broadcast actually stores', () => {
        // The default carries `window`, never `window_minutes`, so reading only the deprecated field
        // reported "0 minutes" for every broadcast on the default goal.
        expect(formatConversionWindow(DEFAULT_BROADCAST_CONVERSION)).toEqual('7d')
    })

    it.each([
        ['12h', '12h'],
        ['30m', '30m'],
        ['45s', '45s'],
        // `humanFriendlyDuration` joins units with a non-breaking space so a duration never wraps.
        ['1.5h', '1h\u00a030m'],
    ])('formats the duration string %s', (window, expected) => {
        expect(formatConversionWindow(conversion({ window }))).toEqual(expected)
    })

    it('falls back to window_minutes for a record saved before the duration form', () => {
        expect(formatConversionWindow(conversion({ window: null, window_minutes: 90 }))).toEqual('1h\u00a030m')
    })

    it('prefers the duration when a record somehow carries both', () => {
        expect(formatConversionWindow(conversion({ window: '7d', window_minutes: 5 }))).toEqual('7d')
    })

    it('returns null when neither is set, so the caller can name the API default', () => {
        expect(formatConversionWindow(conversion({}))).toBeNull()
    })

    it('shows an unparseable window rather than dropping it', () => {
        expect(formatConversionWindow(conversion({ window: 'whenever' }))).toEqual('whenever')
    })
})
