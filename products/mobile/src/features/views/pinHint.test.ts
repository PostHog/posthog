import AsyncStorage from '@react-native-async-storage/async-storage'
import { act, renderHook, waitFor } from '@testing-library/react-native'

import { track } from '@/lib/analytics'
import type { PinDisplay, PinView, ViewKind } from '@/model/views'

import { pinHintTarget, usePinHint } from './pinHint'
import { usePinHintStore } from './pinHintStore'
import type { PinDisplayPrefs } from './smartPinDisplay'

jest.mock('@/lib/analytics', () => ({ track: jest.fn() }))

function pin(id: string, kind: ViewKind, native = true, display: PinDisplay = { mode: 'row' }): PinView {
    return {
        kind,
        ref: id,
        name: id,
        href: null,
        shortcutId: id,
        shortcutIds: [id],
        type: kind,
        serverOrder: 0,
        rank: null,
        display,
        native,
    }
}

const chart: PinDisplay = { mode: 'chart', tileId: 1, insightId: 1 }
const dashboard = pin('dashboard', 'dashboard')
const insight = pin('insight', 'insight')
const web = pin('web', 'web_analytics')
const notebook = pin('notebook', 'notebook', false)

describe('pin hint', () => {
    beforeEach(async () => {
        jest.mocked(track).mockClear()
        usePinHintStore.setState({ dismissed: false })
        await AsyncStorage.clear()
    })

    test.each<[string, PinView[], PinDisplayPrefs, PinDisplayPrefs, string | null]>([
        [
            'picks the first pin with a confirmed visual',
            [dashboard, insight],
            { dashboard: chart, insight: chart },
            {},
            'dashboard',
        ],
        ['skips a pin without an automatic display', [dashboard, insight], { insight: chart }, {}, 'insight'],
        [
            'skips kinds that show as rows only',
            [web, notebook, insight],
            { web: chart, notebook: chart, insight: chart },
            {},
            'insight',
        ],
        [
            'returns null once any pin has a chosen display',
            [dashboard, insight],
            { dashboard: chart },
            { insight: chart },
            null,
        ],
        ['returns null without a confirmed visual', [dashboard, web], {}, {}, null],
    ])('%s', (_name, pins, automatic, explicit, expected) => {
        expect(pinHintTarget(pins, automatic, explicit)?.shortcutId ?? null).toBe(expected)
    })

    test('reports the hint once while it shows, and close hides it for good', async () => {
        const automatic = { dashboard: chart }
        const pins = [{ ...dashboard, display: chart }]
        const { result, rerender } = renderHook(
            (props: { pins: PinView[] }) => usePinHint({ pins: props.pins, automatic, explicit: {}, enabled: true }),
            { initialProps: { pins } }
        )
        await waitFor(() => expect(result.current.target?.shortcutId).toBe('dashboard'))
        rerender({ pins: [...pins] })
        expect(track).toHaveBeenCalledTimes(1)
        expect(track).toHaveBeenCalledWith('mobile_pin_hint_shown', { kind: 'dashboard', mode: 'chart' })

        act(() => result.current.dismiss('close'))
        expect(result.current.target).toBeNull()
        expect(track).toHaveBeenLastCalledWith('mobile_pin_hint_dismissed', { reason: 'close' })
        await waitFor(async () => expect(await AsyncStorage.getItem('views-pin-hint:v1')).toContain('"dismissed":true'))
    })
})
