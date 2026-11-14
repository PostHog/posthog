import { reportMarkdown } from './reportMarkdown'

describe('reportMarkdown', () => {
    const url = 'https://app.example.com/inbox/reports/1'

    test.each([
        [
            'with a summary',
            '## Problem\n\nIt fails.\n',
            `# Fix it\n\n## Problem\n\nIt fails.\n\n[Open the report in PostHog](${url})`,
        ],
        ['with no summary yet', null, `# Fix it\n\n[Open the report in PostHog](${url})`],
    ])('copies a report %s', (_name, summary, expected) => {
        expect(reportMarkdown({ title: 'Fix it', summary }, url)).toBe(expected)
    })
})
