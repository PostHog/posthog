import { scene } from './Group'

describe('Group scene', () => {
    it.each<[string, string]>([
        ['50%25off', '50%off'],
        ['50%off', '50%off'],
        ['foo bar', 'foo bar'],
    ])('paramsToProps turns raw groupKey %s into groupKey %s without throwing', (rawGroupKey, expected) => {
        expect(
            scene.paramsToProps?.({
                params: { groupTypeIndex: '0', groupKey: rawGroupKey },
                searchParams: {},
                hashParams: {},
            })
        ).toEqual({
            groupTypeIndex: 0,
            groupKey: expected,
        })
    })
})
