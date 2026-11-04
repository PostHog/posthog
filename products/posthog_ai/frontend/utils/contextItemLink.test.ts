import { contextItemPath, isOnContextItemPage } from './contextItemLink'

describe('contextItemLink', () => {
    test.each([
        [{ type: 'experiment', key: 17 }, '/experiments/17'],
        [{ type: 'feature_flag', key: 'new-checkout', pageId: 12 }, '/feature-flags/12'],
        [{ type: 'feature_flag', key: '99', pageId: 12 }, '/feature-flags/12'],
        [{ type: 'feature_flag', key: '12' }, null],
        [{ type: 'feature_flag', key: 'new-checkout', pageId: '' }, null],
        [{ type: 'error_tracking_issue', key: 'issue-id' }, '/error_tracking/issue-id'],
        [{ type: 'signal_report', key: 'report-id' }, '/inbox/report-id'],
        [{ type: 'insight', key: 'aBc123' }, '/insights/aBc123'],
        [{ type: 'insight', key: 17, pageId: 'aBc123' }, '/insights/aBc123'],
        [{ type: 'notebook', key: 'note123' }, '/notebooks/note123'],
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
        ['/project/1/notebooks/note123/', '/notebooks/note123', true],
        ['/project/1/experiments/170', '/experiments/17', false],
        ['/project/1/feature-flags/12', '/experiments/17', false],
    ])('on %s, the page %s is current: %s', (pathname, path, expected) => {
        expect(isOnContextItemPage(path, pathname)).toBe(expected)
    })
})
