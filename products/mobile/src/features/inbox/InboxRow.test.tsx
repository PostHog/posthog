import { render, screen } from '@testing-library/react-native'

import { buildDemoFixtures } from '@/demo/fixtures'
import type { InboxItem } from '@/model/types'
import { colors } from '@/ui/tokens'

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
const { pullRequestUrl: _url, pullRequestState: _state, ...BASE_ITEM } = fixture.item
const PR_URL = 'https://github.com/example/repo/pull/123'

test.each([
    ['a draft PR', { pullRequestUrl: PR_URL, pullRequestState: 'draft' }, colors.secondary],
    ['an open PR', { pullRequestUrl: PR_URL, pullRequestState: 'open' }, colors.diffGreen],
    ['a merged PR', { pullRequestUrl: PR_URL, pullRequestState: 'merged' }, colors.purple],
    ['no PR URL', {}, undefined],
] as const)('a row with %s shows the matching PR badge', (_case, pullRequest, badgeColor) => {
    const item: InboxItem = { ...BASE_ITEM, state: 'open', ...pullRequest }
    render(<InboxRow item={item} now={NOW} onOpen={jest.fn()} onLongPress={jest.fn()} onSetRead={jest.fn()} />)

    if (badgeColor === undefined) {
        expect(screen.queryByTestId(`inbox-pr-${item.reportId}`)).toBeNull()
    } else {
        expect(screen.getByText('#123')).toHaveStyle({ color: badgeColor })
    }
})
