import { FeatureFlagType } from '~/types'

import { keyBeforeDelete } from './featureFlagKeyLinks'

describe('keyBeforeDelete', () => {
    test.each([
        { name: 'strips its own deleted suffix', key: 'checkout:deleted:5', expected: 'checkout' },
        { name: 'keeps a suffix with another id', key: 'checkout:deleted:7', expected: 'checkout:deleted:7' },
        {
            name: 'keeps a suffix that is not at the end',
            key: 'checkout:deleted:5-v2',
            expected: 'checkout:deleted:5-v2',
        },
        { name: 'keeps a plain key', key: 'checkout', expected: 'checkout' },
    ])('$name', ({ key, expected }) => {
        expect(keyBeforeDelete({ id: 5, key } as FeatureFlagType)).toBe(expected)
    })
})
