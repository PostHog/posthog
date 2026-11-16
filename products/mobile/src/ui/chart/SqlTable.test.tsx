import { act, fireEvent, render, screen } from '@testing-library/react-native'
import { useColorScheme } from 'react-native'

import { sqlPresentation } from '@/model/adapters/sqlVisualization'
import type { SqlColumnView, SqlTableView } from '@/model/views'
import { darkColors, lightColors, type ThemeColors } from '@/ui/theme'

import { SqlTable } from './SqlTable'

jest.mock('react-native-worklets', () => jest.requireActual('react-native-worklets/src/mock'))
jest.mock('react-native-reanimated', () => jest.requireActual('react-native-reanimated/mock'))
jest.mock('@/lib/analytics', () => ({ track: jest.fn() }))

const COLUMNS: [SqlColumnView, SqlColumnView, SqlColumnView] = [
    { name: 'page', scalar: 'STRING', isNumerical: false, isDate: false, format: null },
    { name: 'views', scalar: 'INTEGER', isNumerical: true, isDate: false, format: null },
    {
        name: 'bounce',
        scalar: 'FLOAT',
        isNumerical: true,
        isDate: false,
        format: sqlPresentation({ formatting: { style: 'percent', decimalPlaces: 1 } }),
    },
]

function table(rowCount: number, hasMore = false): SqlTableView {
    return {
        columns: COLUMNS,
        rows: Array.from({ length: rowCount }, (_, index) => [
            `/page-${index}`,
            100 - index,
            index === 0 ? null : 0.25,
        ]),
        hasMore,
    }
}

describe('SqlTable', () => {
    afterEach(() => {
        jest.useRealTimers()
        jest.mocked(useColorScheme).mockReturnValue('light')
    })

    test.each<['light' | 'dark', ThemeColors]>([
        ['light', lightColors],
        ['dark', darkColors],
    ])('shows the header, formatted cells and a muted dash for null in the %s scheme', (scheme, colors) => {
        jest.mocked(useColorScheme).mockReturnValue(scheme)
        render(<SqlTable table={table(2)} label="Top pages" testID="chart-table" />)

        expect(screen.getByText('page')).toBeTruthy()
        expect(screen.getByText('bounce')).toBeTruthy()
        expect(screen.getByText('/page-1')).toBeTruthy()
        expect(screen.getByText('25.0%')).toBeTruthy()
        expect(screen.getByText('–')).toHaveStyle({ color: colors.tertiary })
        expect(screen.getByTestId('chart-table')).toHaveProp(
            'accessibilityLabel',
            'Top pages. Table, 2 rows, 3 columns: page, views, bounce'
        )
    })

    test('cuts a tile to maxRows and opens the rest from "+N more"', () => {
        const onPressMore = jest.fn()
        render(
            <SqlTable
                table={table(10, true)}
                label="Top pages"
                maxRows={6}
                onPressMore={onPressMore}
                testID="chart-table"
            />
        )

        expect(screen.getByTestId('chart-table-row-5')).toBeTruthy()
        expect(screen.queryByTestId('chart-table-row-6')).toBeNull()
        expect(screen.queryByTestId('chart-table-has-more')).toBeNull()
        expect(screen.getByTestId('chart-table')).toHaveProp(
            'accessibilityLabel',
            'Top pages. Table, first 6 of 10+ rows, 3 columns: page, views, bounce'
        )
        fireEvent.press(screen.getByText('+4 more'))
        expect(onPressMore).toHaveBeenCalledTimes(1)
    })

    test('pins the first column when the columns do not fit, and highlights a row in both parts', () => {
        render(<SqlTable table={table(2)} label="Top pages" testID="chart-table" />)
        expect(screen.queryByTestId('chart-table-row-0-pinned')).toBeNull()
        expect(screen.getByTestId('chart-table-scroll')).toHaveProp('scrollEnabled', false)

        fireEvent(screen.getByTestId('chart-table'), 'layout', { nativeEvent: { layout: { width: 200 } } })

        expect(screen.getByTestId('chart-table-scroll')).toHaveProp('scrollEnabled', true)
        expect(screen.getByTestId('chart-table-row-0-pinned')).toHaveTextContent('/page-0')
        expect(screen.getByTestId('chart-table-row-0')).not.toHaveTextContent('/page-0', { exact: false })

        fireEvent.press(screen.getByTestId('chart-table-row-1'))

        const highlighted = { backgroundColor: lightColors.blueHighlight }
        expect(screen.getByTestId('chart-table-row-1-pinned')).toHaveStyle(highlighted)
        expect(screen.getByTestId('chart-table-row-1')).toHaveStyle(highlighted)
        expect(screen.getByTestId('chart-table-row-0-pinned')).not.toHaveStyle(highlighted)
    })

    test.each(['last', 'first', 'only'] as const)(
        'fits a large number in the %s column and lets the user scroll to it',
        (position) => {
            jest.useFakeTimers()
            const number = '9223372036854775807'
            const textColumn = COLUMNS[0]
            const numberColumn = COLUMNS[1]
            const columns =
                position === 'only'
                    ? [numberColumn]
                    : position === 'first'
                      ? [numberColumn, textColumn]
                      : [textColumn, numberColumn]
            const rows = [columns.map((column) => (column.isNumerical ? number : 'Example'))]
            const { rerender } = render(
                <SqlTable table={{ columns, rows, hasMore: false }} label="Large values" testID="chart-table" />
            )
            fireEvent(screen.getByTestId('chart-table'), 'layout', { nativeEvent: { layout: { width: 240 } } })
            expect(screen.getByTestId('chart-table-scroll')).toHaveProp('scrollEnabled', false)

            const columnIndex = columns.findIndex((column) => column.isNumerical)
            fireEvent(
                screen.getByTestId(`chart-table-measure-${columnIndex}`, { includeHiddenElements: true }),
                'layout',
                {
                    nativeEvent: { layout: { width: 300 } },
                }
            )
            act(() => jest.runOnlyPendingTimers())

            expect(screen.getByText(number)).toBeTruthy()
            expect(screen.getByTestId('chart-table-scroll')).toHaveProp('scrollEnabled', true)
            expect(screen.getByTestId('chart-table-scroll')).toHaveProp('showsHorizontalScrollIndicator', true)
            if (position !== 'last') {
                expect(screen.queryByTestId('chart-table-row-0-pinned')).toBeNull()
            }

            rerender(
                <SqlTable
                    table={{ columns: columns.map((column) => ({ ...column })), rows, hasMore: false }}
                    label="Large values"
                    testID="chart-table"
                />
            )
            expect(screen.getByTestId('chart-table-scroll')).toHaveProp('scrollEnabled', true)
        }
    )

    test('draws a screen up to the row cap and says so under the rows', () => {
        render(<SqlTable table={table(501)} label="Top pages" testID="chart-table" />)

        expect(screen.getByTestId('chart-table-row-499')).toBeTruthy()
        expect(screen.queryByTestId('chart-table-row-500')).toBeNull()
        expect(screen.queryByText('+1 more')).toBeNull()
        expect(screen.getByTestId('chart-table-has-more')).toHaveTextContent('First 500 of 501 rows')
    })

    test('says the server cut the result when every row it sent is shown', () => {
        render(<SqlTable table={table(3, true)} label="Top pages" testID="chart-table" />)

        expect(screen.getByTestId('chart-table-has-more')).toHaveTextContent('First 3 rows')
    })
})
