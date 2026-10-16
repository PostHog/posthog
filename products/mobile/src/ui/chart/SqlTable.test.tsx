import { fireEvent, render, screen } from '@testing-library/react-native'

import { sqlPresentation } from '@/model/adapters/sqlVisualization'
import type { SqlColumnView, SqlTableView } from '@/model/views'
import { colors } from '@/ui/tokens'

import { SqlTable } from './SqlTable'

jest.mock('react-native-worklets', () => jest.requireActual('react-native-worklets/src/mock'))
jest.mock('react-native-reanimated', () => jest.requireActual('react-native-reanimated/mock'))
jest.mock('@/lib/analytics', () => ({ track: jest.fn() }))

const COLUMNS: SqlColumnView[] = [
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
    test('shows the header, formatted cells and a muted dash for null', () => {
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

        const highlighted = { backgroundColor: colors.blueHighlight }
        expect(screen.getByTestId('chart-table-row-1-pinned')).toHaveStyle(highlighted)
        expect(screen.getByTestId('chart-table-row-1')).toHaveStyle(highlighted)
        expect(screen.getByTestId('chart-table-row-0-pinned')).not.toHaveStyle(highlighted)
    })

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
