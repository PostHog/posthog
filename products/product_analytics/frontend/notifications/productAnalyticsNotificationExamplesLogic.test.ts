import { PA_MESSAGE_FIELD_LIMITS } from 'scenes/hog-functions/sub-templates/sub-templates'

import { parseExampleRows } from './productAnalyticsNotificationExamplesLogic'

// Rows arrive positionally: [use_case, page, browser].
const RAGECLICK_ROW = ['rageclick', '/pricing', 'Chrome']

describe('parseExampleRows', () => {
    it('maps a rageclick example from its positional columns', () => {
        expect(parseExampleRows([RAGECLICK_ROW])).toEqual({
            rageclick: {
                page: '/pricing',
                browser: 'Chrome',
            },
        })
    })

    // A half-real example (project's page, our invented browser) reads as genuine but isn't,
    // so an incomplete row is dropped in favour of the honest sample copy.
    it.each([
        ['missing page', ['rageclick', '', 'Chrome']],
        ['missing browser', ['rageclick', '/pricing', null]],
        ['an unrecognized use case', ['something-else', '/pricing', 'Chrome']],
    ])('drops a row with %s', (_label, row) => {
        expect(parseExampleRows([row])).toEqual({})
    })

    it('cuts a field at the limit the delivered message uses', () => {
        const page = '/'.concat('x'.repeat(PA_MESSAGE_FIELD_LIMITS.page + 50))

        const parsed = parseExampleRows([['rageclick', page, 'Chrome']])

        expect(parsed['rageclick']?.page).toHaveLength(PA_MESSAGE_FIELD_LIMITS.page)
    })
})
