import { fireEvent, render, screen } from '@testing-library/react-native'

import { NoticeRow } from './NoticeRow'
import type { SessionNoticeItem } from './types'

const NOTICE: SessionNoticeItem = {
    kind: 'notice',
    id: 'background-review',
    tone: 'completed',
    text: 'The background review finished. The report filters and export dialog are ready to inspect.',
}

function measureLines(count: number): void {
    fireEvent(
        screen.getByTestId(`session-notice-measure-${NOTICE.id}`, { includeHiddenElements: true }),
        'textLayout',
        {
            nativeEvent: { lines: Array.from({ length: count }, () => ({ text: 'A measured line' })) },
        }
    )
}

describe('NoticeRow', () => {
    test('previews long notices, expands their full text, and collapses them again', () => {
        render(<NoticeRow item={NOTICE} />)
        measureLines(4)

        expect(screen.getAllByText(NOTICE.text)).toHaveLength(1)
        expect(screen.getByText(NOTICE.text)).toHaveProp('numberOfLines', 2)
        expect(screen.getByRole('button')).toHaveProp('accessibilityState', { expanded: false })

        fireEvent.press(screen.getByText('Show more'))
        expect(screen.getByText(NOTICE.text).props.numberOfLines).toBeUndefined()
        expect(screen.getByRole('button')).toHaveProp('accessibilityState', { expanded: true })

        fireEvent.press(screen.getByText('Show less'))
        expect(screen.getByText(NOTICE.text)).toHaveProp('numberOfLines', 2)
        expect(screen.getByText('Show more')).toBeTruthy()
    })

    test.each([1, 2])('keeps a %i-line notice plain and responds when wrapping changes', (lines) => {
        render(<NoticeRow item={NOTICE} />)
        measureLines(lines)
        expect(screen.queryByRole('button')).toBeNull()

        measureLines(3)
        fireEvent.press(screen.getByText('Show more'))
        expect(screen.getByText('Show less')).toBeTruthy()

        measureLines(lines)
        expect(screen.queryByRole('button')).toBeNull()
        expect(screen.getByText(NOTICE.text)).toHaveProp('numberOfLines', 2)

        measureLines(3)
        expect(screen.getByRole('button')).toHaveProp('accessibilityState', { expanded: false })
    })
})
