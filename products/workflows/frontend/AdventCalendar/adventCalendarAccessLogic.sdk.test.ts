/**
 * @jest-environment-options {"url": "https://app.example.com/project/1"}
 */
import { MOCK_DEFAULT_ORGANIZATION, MOCK_DEFAULT_TEAM, MOCK_DEFAULT_USER } from 'lib/api.mock'

import { FEATURE_FLAGS } from 'lib/constants'

import { ProductItemCategory } from '~/queries/schema/schema-general'
import { AppContext, PreflightStatus, Realm, UserType } from '~/types'

jest.unmock('posthog-js')
jest.mock('~/toolbar/shared/toolbarPosthogJS', () => ({
    toolbarPosthogJS: {},
    captureToolbarException: jest.fn(),
    useToolbarFeatureFlag: () => false,
}))

const FLAG = FEATURE_FLAGS.WORKFLOWS_ADVENT_CALENDAR
const PROJECT_TOKEN = 'phc_example'

const USER: UserType = {
    ...MOCK_DEFAULT_USER,
    realm: Realm.Cloud,
    team: { ...MOCK_DEFAULT_TEAM, uuid: 'project-a', name: 'Project a' },
    organization: { ...MOCK_DEFAULT_ORGANIZATION, customer_id: 'cus_example' },
}

type Reply = 'blocked' | 'flag on' | 'flag off' | 'bad gateway'
type PageDecision = 'on' | 'off' | 'left out'
type Opened = 'before the first reply' | 'after the first reply'

function enabledFlag(key: string): Record<string, unknown> {
    return { key, enabled: true, reason: { code: 'condition_match' }, metadata: { id: 1, version: 1 } }
}

function flagsResponse(reply: Reply): Response {
    if (reply === 'blocked') {
        throw new TypeError('Failed to fetch')
    }
    if (reply === 'bad gateway') {
        return new Response('Bad gateway', { status: 502 })
    }
    const keys = reply === 'flag on' ? [FLAG, 'other-flag'] : ['other-flag']
    return new Response(JSON.stringify({ flags: Object.fromEntries(keys.map((key) => [key, enabledFlag(key)])) }), {
        status: 200,
    })
}

describe('adventCalendarAccessLogic with posthog-js', () => {
    beforeEach(() => {
        jest.useFakeTimers()
        localStorage.clear()
        sessionStorage.clear()
        for (const cookie of document.cookie.split(';')) {
            const name = cookie.split('=')[0].trim()
            for (const domain of ['', '; domain=.example.com']) {
                document.cookie = `${name}=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/${domain}`
            }
        }
        window.JS_POSTHOG_API_KEY = PROJECT_TOKEN
        window.JS_POSTHOG_HOST = 'https://us.example.com'
    })

    afterEach(() => {
        jest.useRealTimers()
        delete window.POSTHOG_GLOBAL_ERRORS
        delete window.POSTHOG_FEATURE_FLAGS_LOADED
    })

    async function openThePage(page: PageDecision, firstReply: Reply): Promise<(next: Reply) => void> {
        jest.resetModules()
        delete window.POSTHOG_GLOBAL_ERRORS
        delete window.POSTHOG_FEATURE_FLAGS_LOADED
        let reply = firstReply
        global.fetch = jest.fn(async (url: RequestInfo | URL) => {
            if (String(url).includes('/flags/')) {
                return flagsResponse(reply)
            }
            return new Response('{}', { status: 200 })
        }) as typeof fetch
        window.POSTHOG_APP_CONTEXT = {
            current_user: USER,
            preflight: { site_url: 'https://posthog.example.com' } as PreflightStatus,
        } as AppContext
        window.POSTHOG_USER_IDENTITY_WITH_FLAGS = {
            distinctID: USER.distinct_id,
            featureFlags: page === 'left out' ? { 'other-flag': true } : { 'other-flag': true, [FLAG]: page === 'on' },
        }

        const { loadPostHogJS } = await import('~/loadPostHogJS')
        const { initKea } = await import('~/initKea')

        loadPostHogJS()
        initKea()
        ;(window as any)._POSTHOG_REMOTE_CONFIG = { [PROJECT_TOKEN]: { config: {} } }
        document.querySelector<HTMLScriptElement>('script[src*="/config.js"]')?.onload?.(new Event('load'))
        return (next) => {
            reply = next
        }
    }

    async function openCalendar(
        page: PageDecision,
        replies: Reply[],
        opened: Opened
    ): Promise<(boolean | undefined)[]> {
        const replyNext = await openThePage(page, replies[0])
        const posthog = (await import('posthog-js')).default
        const { adventCalendarAccessLogic } = await import('./adventCalendarAccessLogic')

        const logic = adventCalendarAccessLogic()
        if (opened === 'before the first reply') {
            logic.mount()
        }
        await jest.advanceTimersByTimeAsync(1000)
        if (opened === 'after the first reply') {
            logic.mount()
        }
        const seen = [logic.values.calendarOn]
        for (const next of replies.slice(1)) {
            replyNext(next)
            posthog.reloadFeatureFlags()
            await jest.advanceTimersByTimeAsync(1000)
            seen.push(logic.values.calendarOn)
        }
        logic.unmount()
        return seen
    }

    async function seeTheEntryPoints(page: PageDecision, failure: Reply): Promise<{ card: boolean; tree: boolean }> {
        await openThePage(page, failure)
        const { createElement } = await import('react')
        const { act, cleanup, render } = await import('@testing-library/react/pure')
        const { CustomCategorySuffix } = await import('~/layout/panel-layout/ProjectTree/CustomCategorySuffix')
        const { AdventEntry } = await import('./entry/AdventEntry')

        await jest.advanceTimersByTimeAsync(1000)
        const { container } = render(
            createElement(
                'div',
                null,
                createElement(AdventEntry),
                createElement(CustomCategorySuffix, { category: ProductItemCategory.MESSAGING, nav: 'classic' })
            )
        )
        await act(() => jest.advanceTimersByTimeAsync(1000))
        const seen = {
            card: container.querySelector('[data-attr="advent-entry-card"]') !== null,
            tree: container.querySelector('[data-attr="advent-entry-nav-tree"]') !== null,
        }
        cleanup()
        return seen
    }

    it.each<[string, PageDecision, Reply[], (boolean | undefined)[]]>([
        ['a blocked load shows the page decision on', 'on', ['blocked'], [true]],
        ['a bad gateway shows the page decision on', 'on', ['bad gateway'], [true]],
        ['a blocked load on a page that left the flag out follows the SDK', 'left out', ['blocked'], [false]],
        ['a successful load wins over the page decision', 'on', ['flag off'], [false]],
        ['a successful retry after a blocked load shows the loaded flag', 'on', ['blocked', 'flag off'], [true, false]],
        [
            'a failed refresh after a successful load keeps the loaded flag on',
            'off',
            ['flag on', 'blocked'],
            [true, true],
        ],
        [
            'a failed refresh after a successful load keeps the loaded flag off',
            'on',
            ['flag off', 'blocked'],
            [false, false],
        ],
    ])('%s', async (_name, page, replies, expected) => {
        for (const opened of ['before the first reply', 'after the first reply'] as const) {
            expect({ opened, seen: await openCalendar(page, replies, opened) }).toEqual({ opened, seen: expected })
        }
    })

    it.each<[string, Reply, PageDecision, Reply, boolean]>([
        ['a returning visitor stored without the flag sees the page decision on', 'flag off', 'on', 'blocked', true],
        [
            'a returning visitor stored without the flag sees the page decision on',
            'flag off',
            'on',
            'bad gateway',
            true,
        ],
        ['a returning visitor stored with the flag on sees the page decision off', 'flag on', 'off', 'blocked', false],
        [
            'a returning visitor stored with the flag on keeps it when the page leaves the flag out',
            'flag on',
            'left out',
            'blocked',
            true,
        ],
    ])(
        '%s (earlier reply %s, page %s) when the next page gets %s',
        async (_name, earlierReply, page, failure, expected) => {
            await openCalendar('on', [earlierReply], 'after the first reply')

            for (const opened of ['before the first reply', 'after the first reply'] as const) {
                expect({ opened, seen: await openCalendar(page, [failure], opened) }).toEqual({
                    opened,
                    seen: [expected],
                })
            }
        }
    )

    it.each<[string, Reply, PageDecision, boolean]>([
        ['a returning visitor stored without the flag sees both entry points on', 'flag off', 'on', true],
        ['a returning visitor stored with the flag on sees no entry point off', 'flag on', 'off', false],
    ])('%s when the next page is blocked', async (_name, earlierReply, page, shown) => {
        await openCalendar('on', [earlierReply], 'after the first reply')

        expect(await seeTheEntryPoints(page, 'blocked')).toEqual({ card: shown, tree: shown })
    })
})
