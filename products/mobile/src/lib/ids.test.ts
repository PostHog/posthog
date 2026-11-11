import { isReportId } from './ids'

describe('isReportId', () => {
    test.each([
        ['a report uuid', '0199a2b4-7c1e-7d3f-9a5b-2c4d6e8f0a1b', false, true],
        ['a demo fixture id in demo mode', 'demo-report-load-time', true, true],
        ['a demo fixture id outside demo mode', 'demo-report-load-time', false, false],
        ['a path that leaves the report endpoint', '../../tasks/0199a2b4-7c1e-7d3f-9a5b-2c4d6e8f0a1b', false, false],
        ['a uuid with a query string', '0199a2b4-7c1e-7d3f-9a5b-2c4d6e8f0a1b?view=all', false, false],
        ['an empty id', '', true, false],
    ])('%s', (_name, id, demo, expected) => {
        expect(isReportId(id, demo)).toBe(expected)
    })
})
