import { cleanup, fireEvent, render } from '@testing-library/react'
import posthog from 'posthog-js'

import { initKeaTests } from '~/test/init'

import { TodayRailPreviewItem, TodayRailPreviewList } from './TodayRailPreviewList'

const item = (name: string): TodayRailPreviewItem => ({ name, href: `/insights/${name}`, icon: <span /> })

const railEvents = (capture: jest.SpyInstance): unknown[][] =>
    capture.mock.calls.filter(([event]) => String(event).startsWith('today rail card'))

describe('TodayRailPreviewList usage events', () => {
    let capture: jest.SpyInstance

    beforeEach(() => {
        initKeaTests()
        capture = jest.spyOn(posthog, 'capture').mockImplementation(() => undefined)
    })

    afterEach(() => {
        cleanup()
        capture.mockRestore()
    })

    it('reports a card once per pane, with its counts once loading ends', () => {
        const props = { title: 'Analytics', onAction: () => {} }
        const { rerender } = render(
            <TodayRailPreviewList {...props} pane="analytics" pins={[item('pin')]} recents={[]} loading />
        )
        rerender(
            <TodayRailPreviewList {...props} pane="analytics" pins={[item('pin')]} recents={[item('a'), item('b')]} />
        )
        rerender(
            <TodayRailPreviewList
                {...props}
                pane="analytics"
                pins={[item('pin')]}
                recents={[item('a'), item('b'), item('c')]}
            />
        )
        rerender(<TodayRailPreviewList {...props} pane="people" pins={[item('pin')]} recents={[]} />)

        expect(railEvents(capture)).toEqual([
            ['today rail card shown', { pane: 'analytics', recent_count: 2, pinned_count: 1 }],
            ['today rail card shown', { pane: 'people', recent_count: 0, pinned_count: 1 }],
        ])
    })

    test.each([
        ['a plain click on a recent', 'b', {}, { section: 'recents', position: 1, new_tab: false }],
        ['a Cmd click on a pin', 'pin', { metaKey: true }, { section: 'pinned', position: 0, new_tab: true }],
    ])('reports %s with its section and position', (_, name, modifiers, expected) => {
        const { getByTitle } = render(
            <TodayRailPreviewList
                title="Analytics"
                pane="analytics"
                pins={[item('pin')]}
                recents={[item('a'), item('b')]}
                onAction={() => {}}
            />
        )
        capture.mockClear()

        fireEvent.click(getByTitle(name), modifiers)

        expect(railEvents(capture)).toEqual([['today rail card item opened', { pane: 'analytics', ...expected }]])
    })
})
