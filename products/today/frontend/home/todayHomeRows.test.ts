import { FEATURE_FLAGS } from 'lib/constants'

import { homeItems } from './todayHomeRows'

describe('todayHomeRows', () => {
    test.each([
        [{}, ['today']],
        [{ [FEATURE_FLAGS.PRODUCT_AUTONOMY]: true }, ['today', 'inbox-reports']],
        [{ [FEATURE_FLAGS.SIGNALS_REPORT_MONITORING]: true }, ['today']],
        [
            { [FEATURE_FLAGS.PRODUCT_AUTONOMY]: true, [FEATURE_FLAGS.SIGNALS_REPORT_MONITORING]: true },
            ['today', 'inbox-reports', 'inbox-monitoring'],
        ],
        [{ [FEATURE_FLAGS.PULSE]: true }, ['today', 'pulse']],
    ])('with flags %o, the Home pane shows the rows %o', (flags, keys) => {
        expect(homeItems(flags).map((row) => row.key)).toEqual(keys)
    })
})
