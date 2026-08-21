import { humanizeReportTitle } from './reportPresentation'

describe('humanizeReportTitle', () => {
    it.each([
        ['fix(oauth): validate scopes before redirect', 'Validate scopes before redirect'],
        ['feat: add retention export', 'Add retention export'],
        ['already a plain title', 'Already a plain title'],
        ['', 'Untitled report'],
        [null, 'Untitled report'],
    ])('humanizes %p to %p', (title, expected) => {
        expect(humanizeReportTitle(title, 'Untitled report')).toBe(expected)
    })
})
