import { router } from 'kea-router'
import posthog from 'posthog-js'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { removeProjectIdIfPresent } from 'lib/utils/kea-router'

import { initKeaTests } from '~/test/init'

import { broadcastsSceneLogic } from '../Broadcasts/broadcastsSceneLogic'
import { workflowsSceneLogic } from '../WorkflowsScene'
import { audienceSceneLogic } from './audienceSceneLogic'

type Surface = 'workflows' | 'broadcasts'

const MOVED_TAB_REDIRECTS: { from: string; to: string; surface: Surface; tab: string }[] = [
    { from: '/workflows/opt-outs', to: '/audience/topics', surface: 'workflows', tab: 'opt-outs' },
    { from: '/workflows/suppression', to: '/audience/suppression', surface: 'workflows', tab: 'suppression' },
    { from: '/broadcasts/opt-outs', to: '/audience/topics', surface: 'broadcasts', tab: 'opt-outs' },
    { from: '/broadcasts/suppression', to: '/audience/suppression', surface: 'broadcasts', tab: 'suppression' },
]

const OPENED_BY = ['bookmark', 'click'] as const

const MOVED_TAB_OPENINGS = MOVED_TAB_REDIRECTS.flatMap((redirect) =>
    OPENED_BY.map((openedBy) => ({ ...redirect, openedBy }))
)

const SURFACE_SCENES: Record<Surface, { mount: () => void; currentTab: () => string }> = {
    workflows: {
        mount: () => workflowsSceneLogic().mount(),
        currentTab: () => workflowsSceneLogic().values.currentTab,
    },
    broadcasts: {
        mount: () => broadcastsSceneLogic.mount(),
        currentTab: () => broadcastsSceneLogic.values.currentTab,
    },
}

function openTab(url: string, surface: Surface, openedBy: (typeof OPENED_BY)[number]): void {
    if (openedBy === 'bookmark') {
        router.actions.push(url)
        SURFACE_SCENES[surface].mount()
    } else {
        SURFACE_SCENES[surface].mount()
        router.actions.push(url)
    }
}

function currentPath(): string {
    return removeProjectIdIfPresent(router.values.location.pathname)
}

function redirectEvents(): unknown[][] {
    return jest.mocked(posthog.capture).mock.calls.filter(([event]) => event === 'messaging tab redirected to audience')
}

function setAudienceFlag(enabled: boolean): void {
    featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.WORKFLOWS_AUDIENCE]: enabled })
}

describe('audience routing', () => {
    beforeEach(() => {
        localStorage.clear()
        initKeaTests()
        jest.spyOn(posthog, 'capture')
        featureFlagLogic.mount()
    })

    afterEach(() => {
        jest.restoreAllMocks()
    })

    it.each(MOVED_TAB_OPENINGS)(
        'with the flag on, $from opened by $openedBy is replaced by $to',
        ({ from, to, surface, tab, openedBy }) => {
            setAudienceFlag(true)

            openTab(from, surface, openedBy)

            expect(redirectEvents()).toEqual([['messaging tab redirected to audience', { tab, from: surface }]])
            expect(currentPath()).toBe(to)
            expect(router.values.lastMethod).toBe('REPLACE')
        }
    )

    it.each(MOVED_TAB_OPENINGS)(
        'with the flag off, $from opened by $openedBy stays on its tab',
        ({ from, surface, tab, openedBy }) => {
            setAudienceFlag(false)

            openTab(from, surface, openedBy)

            expect(currentPath()).toBe(from)
            expect(SURFACE_SCENES[surface].currentTab()).toBe(tab)
            expect(redirectEvents()).toEqual([])
        }
    )

    it('redirects a moved tab once when the flags arrive after it opened', () => {
        openTab('/broadcasts/suppression', 'broadcasts', 'bookmark')
        expect(currentPath()).toBe('/broadcasts/suppression')

        setAudienceFlag(true)

        expect(currentPath()).toBe('/audience/suppression')
        expect(router.values.lastMethod).toBe('REPLACE')
        expect(redirectEvents()).toEqual([
            ['messaging tab redirected to audience', { tab: 'suppression', from: 'broadcasts' }],
        ])
    })

    it('leaves other tabs alone when the flags arrive', () => {
        openTab('/workflows/library', 'workflows', 'bookmark')

        setAudienceFlag(true)

        expect(currentPath()).toBe('/workflows/library')
    })

    it.each([
        { visited: ['/audience'], tab: 'topics', label: 'Topics' },
        { visited: ['/audience/topics'], tab: 'topics', label: 'Topics' },
        { visited: ['/audience/suppression'], tab: 'suppression', label: 'Suppression list' },
        { visited: ['/audience/suppression', '/audience'], tab: 'topics', label: 'Topics' },
        { visited: ['/audience/not-a-tab'], tab: 'topics', label: 'Topics' },
        { visited: ['/audience/recipients/jamie%40example.com'], tab: 'topics', label: 'Topics' },
    ])('after visiting $visited, Audience shows the $tab tab', ({ visited, tab, label }) => {
        audienceSceneLogic.mount()

        visited.forEach((url) => router.actions.push(url))

        expect(audienceSceneLogic.values.currentTab).toBe(tab)
        expect(audienceSceneLogic.values.breadcrumbs.map(({ name }) => name)).toEqual([label])
    })
})
