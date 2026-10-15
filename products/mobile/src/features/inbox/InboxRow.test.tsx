import { render, screen } from '@testing-library/react-native'

import { buildDemoFixtures } from '@/demo/fixtures'
import type { InboxItem } from '@/model/types'

import { InboxRow } from './InboxRow'

jest.mock('react-native-worklets', () => jest.requireActual('react-native-worklets/src/mock'))
jest.mock('react-native-reanimated', () => ({
    ...jest.requireActual('react-native-reanimated/mock'),
    useReducedMotion: () => true,
}))
jest.mock('@/lib/analytics', () => ({ track: jest.fn() }))

const NOW = new Date(2026, 9, 14)
const fixture = buildDemoFixtures(NOW).list[0]
if (!fixture) {
    throw new Error('Missing demo report')
}
const { pullRequestUrl: _ignored, ...BASE_ITEM } = fixture.item

test.each([
    ['a numbered PR URL', 'https://github.com/example/repo/pull/123', '#123'],
    ['no PR URL', undefined, undefined],
])('a row with %s shows the matching PR badge', (_case, pullRequestUrl, badge) => {
    const item: InboxItem = pullRequestUrl ? { ...BASE_ITEM, pullRequestUrl } : BASE_ITEM
    render(<InboxRow item={item} now={NOW} onOpen={jest.fn()} onLongPress={jest.fn()} onSetRead={jest.fn()} />)

    const found = screen.queryByTestId(`inbox-pr-${item.reportId}`)
    if (badge === undefined) {
        expect(found).toBeNull()
    } else {
        expect(found).toHaveTextContent(badge)
    }
})
