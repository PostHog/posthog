import { sqlPresentation } from '@/model/adapters/sqlVisualization'
import type { SqlCell, SqlColumnView } from '@/model/views'

import { formatSqlCell, sqlRowsText } from './sqlCellFormat'

const NOW = new Date(2026, 9, 16, 12).getTime()

function column(scalar: string, formatting?: Record<string, unknown>): SqlColumnView {
    return {
        name: 'value',
        scalar,
        isNumerical: scalar === 'INTEGER' || scalar === 'FLOAT' || scalar === 'DECIMAL',
        isDate: scalar === 'DATE' || scalar === 'DATETIME',
        format: sqlPresentation(formatting ? { formatting } : undefined),
    }
}

describe('SQL table cells', () => {
    test.each<[string, SqlCell, SqlColumnView, string | null]>([
        ['null as an empty cell', null, column('INTEGER'), null],
        ['a number without settings as written', 1234567, column('INTEGER'), '1234567'],
        ['number style with separators', 1234567.891, column('FLOAT', { style: 'number' }), '1,234,567.891'],
        [
            'number style keeping fixed decimals',
            1234.5,
            column('FLOAT', { style: 'number', decimalPlaces: 2 }),
            '1,234.50',
        ],
        ['short style', 12345, column('INTEGER', { style: 'short' }), '12.3\u00a0K'],
        ['short style in millions', 1_250_000, column('INTEGER', { style: 'short' }), '1.25\u00a0M'],
        ['percent scaled by 100', 0.1234, column('FLOAT', { style: 'percent', decimalPlaces: 1 }), '12.3%'],
        ['prefix and suffix', 42, column('INTEGER', { prefix: '$', suffix: ' USD' }), '$42 USD'],
        ['none style with decimals', 1.23456, column('FLOAT', { decimalPlaces: 2 }), '1.23'],
        ['a decimal sent as a string', '1234.5', column('DECIMAL', { style: 'number' }), '1,234.5'],
        ['a numeric string that is not a number', 'n/a', column('DECIMAL'), 'n/a'],
        ['a hex string as text', '0x10', column('DECIMAL', { style: 'number' }), '0x10'],
        ['a wide integer string with its digits', '18446744073709551615', column('INTEGER'), '18446744073709551615'],
        [
            'a wide integer string with a style',
            '18446744073709551615',
            column('INTEGER', { style: 'short' }),
            '18.4\u00a0E',
        ],
        ['a boolean', true, column('BOOLEAN'), 'true'],
        ['a boolean sent as 0', 0, column('BOOLEAN'), 'false'],
        ['a date this year', '2026-10-03', column('DATE'), 'Oct 3'],
        ['a date in another year', '2025-10-03', column('DATE'), 'Oct 3, 2025'],
        ['a datetime in its own wall clock', '2026-10-03T14:05:00-07:00', column('DATETIME'), 'Oct 3, 14:05'],
        ['a date that does not parse', 'someday', column('DATE'), 'someday'],
    ])('formats %s', (_case, cell, col, expected) => {
        expect(formatSqlCell(cell, col, NOW)).toBe(expected)
    })

    test.each([
        [{ rows: [[1], [2]], hasMore: false }, '2 rows'],
        [{ rows: [[1]], hasMore: false }, '1 row'],
        [{ rows: Array.from({ length: 100 }, () => [1]), hasMore: true }, 'First 100 rows'],
    ])('counts rows as %#', (table, expected) => {
        expect(sqlRowsText(table)).toBe(expected)
    })
})
