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

const MOUNT_SURFACE_SCENE: Record<Surface, () => void> = {
    workflows: () => workflowsSceneLogic().mount(),
    broadcasts: () => broadcastsSceneLogic.mount(),
}

function openTab(url: string, surface: Surface, openedBy: (typeof OPENED_BY)[number]): void {
    if (openedBy === 'bookmark') {
        router.actions.push(url)
        MOUNT_SURFACE_SCENE[surface]()
    } else {
        MOUNT_SURFACE_SCENE[surface]()
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
        initKeaTests()
        jest.spyOn(posthog, 'capture')
        featureFlagLogic.mount()
    })

    afterEach(() => {
        jest.restoreAllMocks()
    })

    it.each(MOVED_TAB_REDIRECTS.flatMap((redirect) => OPENED_BY.map((openedBy) => ({ ...redirect, openedBy }))))(
        'with the flag on, $from opened by $openedBy is replaced by $to',
        ({ from, to, surface, tab, openedBy }) => {
            setAudienceFlag(true)

            openTab(from, surface, openedBy)

            expect(redirectEvents()).toEqual([['messaging tab redirected to audience', { tab, from: surface }]])
            expect(currentPath()).toBe(to)
            expect(router.values.lastMethod).toBe('REPLACE')
        }
    )

    it.each(MOVED_TAB_REDIRECTS)('with the flag off, $from stays put', ({ from, surface }) => {
        setAudienceFlag(false)

        openTab(from, surface, 'click')

        expect(currentPath()).toBe(from)
        expect(redirectEvents()).toEqual([])
    })

    it('redirects a moved tab that opened before the flags arrived', () => {
        openTab('/broadcasts/suppression', 'broadcasts', 'bookmark')

        setAudienceFlag(true)

        expect(currentPath()).toBe('/audience/suppression')
    })

    it('leaves other tabs alone when the flags arrive', () => {
        openTab('/workflows/library', 'workflows', 'bookmark')

        setAudienceFlag(true)

        expect(currentPath()).toBe('/workflows/library')
    })

    it.each([
        { visited: ['/audience'], tab: 'topics' },
        { visited: ['/audience/topics'], tab: 'topics' },
        { visited: ['/audience/suppression'], tab: 'suppression' },
        { visited: ['/audience/suppression', '/audience'], tab: 'topics' },
        { visited: ['/audience/not-a-tab'], tab: 'topics' },
        { visited: ['/audience/recipients/jamie%40example.com'], tab: 'topics' },
    ])('after visiting $visited, Audience shows the $tab tab', ({ visited, tab }) => {
        audienceSceneLogic.mount()

        visited.forEach((url) => router.actions.push(url))

        expect(audienceSceneLogic.values.currentTab).toBe(tab)
    })
})
