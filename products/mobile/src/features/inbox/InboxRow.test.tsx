import { render, screen } from '@testing-library/react-native'
import { useColorScheme } from 'react-native'

import { buildDemoFixtures } from '@/demo/fixtures'
import type { InboxItem } from '@/model/types'
import { themes } from '@/ui/theme'

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
const light = themes.light.colors
const dark = themes.dark.colors

describe('InboxRow', () => {
    afterEach(() => {
        jest.mocked(useColorScheme).mockReturnValue('light')
    })

    test.each([
        ['a draft PR', 'light', { pullRequestUrl: PR_URL, pullRequestState: 'draft' }, light.secondary],
        ['an open PR', 'light', { pullRequestUrl: PR_URL, pullRequestState: 'open' }, light.diffGreen],
        ['a merged PR', 'light', { pullRequestUrl: PR_URL, pullRequestState: 'merged' }, light.purple],
        ['an open PR', 'dark', { pullRequestUrl: PR_URL, pullRequestState: 'open' }, dark.diffGreen],
        ['no PR URL', 'light', {}, undefined],
    ] as const)('a row with %s in %s mode shows the matching PR badge', (_case, scheme, pullRequest, badgeColor) => {
        jest.mocked(useColorScheme).mockReturnValue(scheme)
        const item: InboxItem = { ...BASE_ITEM, state: 'open', ...pullRequest }
        render(<InboxRow item={item} now={NOW} onOpen={jest.fn()} onLongPress={jest.fn()} onSetRead={jest.fn()} />)

        if (badgeColor === undefined) {
            expect(screen.queryByTestId(`inbox-pr-${item.reportId}`)).toBeNull()
        } else {
            expect(screen.getByText('#123')).toHaveStyle({ color: badgeColor })
        }
    })
})
