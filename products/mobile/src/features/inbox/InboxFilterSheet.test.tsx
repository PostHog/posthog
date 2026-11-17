import { fireEvent, render, screen } from '@testing-library/react-native'

import { FEATURE_FLAGS, setFeatureFlags } from '@/lib/featureFlags'
import type { InboxItem } from '@/model/types'
import { OverlayHost } from '@/ui/OverlayPortal'

import { DEFAULT_INBOX_FILTERS, type InboxFilters } from './filters'
import { InboxFilterSheet } from './InboxFilterSheet'

jest.mock('react-native-worklets', () => jest.requireActual('react-native-worklets/src/mock'))
jest.mock('react-native-reanimated', () => ({
    ...jest.requireActual('react-native-reanimated/mock'),
    useReducedMotion: () => true,
}))
jest.mock(
    'react-native-safe-area-context',
    () => jest.requireActual('react-native-safe-area-context/jest/mock').default
)

function item(id: string, sources: string[]): InboxItem {
    return {
        id,
        reportId: id,
        title: id,
        sourceProduct: 'error_tracking',
        sourceLabel: 'Error',
        sources,
        accent: 'alert',
        createdAt: '2026-10-18T12:00:00Z',
        updatedAt: '2026-10-18T12:00:00Z',
        modelScore: null,
        state: 'open',
        needsInput: false,
        read: false,
    }
}

const ITEMS = [item('a', ['error_tracking']), item('b', ['github'])]

function renderSheet(filters: InboxFilters = DEFAULT_INBOX_FILTERS): {
    onToggleSource: jest.Mock
    onClear: jest.Mock
} {
    const onToggleSource = jest.fn()
    const onClear = jest.fn()
    render(
        <InboxFilterSheet
            visible
            onClose={jest.fn()}
            filters={filters}
            items={ITEMS}
            onSortChange={jest.fn()}
            onCreatedWindowChange={jest.fn()}
            onToggleSource={onToggleSource}
            onClear={onClear}
        />,
        { wrapper: OverlayHost }
    )
    return { onToggleSource, onClear }
}

describe('InboxFilterSheet', () => {
    beforeEach(() => setFeatureFlags({}))

    test.each([
        [true, 1],
        [false, 0],
    ])('shows the model score sort only when the flag is on (%s)', (on, rows) => {
        setFeatureFlags({ [FEATURE_FLAGS.modelScoreSort]: on })
        renderSheet()
        expect(screen.getByTestId('inbox-sort-newest')).toBeOnTheScreen()
        expect(screen.queryAllByTestId('inbox-sort-model_score')).toHaveLength(rows)
    })

    test('offers the loaded sources and toggles the pressed one', () => {
        const { onToggleSource } = renderSheet()
        expect(screen.queryByTestId('inbox-source-linear')).toBeNull()
        fireEvent.press(screen.getByTestId('inbox-source-github'))
        expect(onToggleSource).toHaveBeenCalledWith('github')
    })

    test('enables Clear only when a filter differs from the defaults', () => {
        const { onClear } = renderSheet()
        expect(screen.getByTestId('inbox-filters-clear')).toBeDisabled()
        fireEvent.press(screen.getByTestId('inbox-filters-clear'))
        expect(onClear).not.toHaveBeenCalled()

        screen.unmount()
        const changed = renderSheet({ ...DEFAULT_INBOX_FILTERS, createdWindow: '7d' })
        expect(screen.getByTestId('inbox-filters-clear')).toBeEnabled()
        fireEvent.press(screen.getByTestId('inbox-filters-clear'))
        expect(changed.onClear).toHaveBeenCalledTimes(1)
    })
})
