import { contextItemPath, isOnContextItemPage } from './contextItemLink'

describe('contextItemLink', () => {
    test.each([
        [{ type: 'experiment', key: 17 }, '/experiments/17'],
        [{ type: 'feature_flag', key: 12 }, '/feature-flags/12'],
        [{ type: 'insight', key: 'aBc123' }, '/insights/aBc123'],
        // An event item's key is the event name, and the event page needs a definition id.
        [{ type: 'event', key: '$pageview' }, null],
        [{ type: 'text', value: 'Some note' }, null],
        [{ type: 'experiment' }, null],
    ])('links %o to %s', (item, expected) => {
        expect(contextItemPath(item)).toEqual(expected)
    })

    test.each([
        ['/project/1/experiments/17', '/experiments/17', true],
        ['/project/1/experiments/17/', '/experiments/17', true],
        ['/project/1/experiments/170', '/experiments/17', false],
        ['/project/1/feature-flags/12', '/experiments/17', false],
    ])('on %s, the page %s is current: %s', (pathname, path, expected) => {
        expect(isOnContextItemPage(path, pathname)).toBe(expected)
    })
})
