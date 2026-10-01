import { router } from 'kea-router'
import posthog from 'posthog-js'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { removeProjectIdIfPresent } from 'lib/utils/kea-router'

import { initKeaTests } from '~/test/init'

import { broadcastsSceneLogic } from '../Broadcasts/broadcastsSceneLogic'
import { workflowsSceneLogic } from '../WorkflowsScene'
import { audienceSceneLogic } from './audienceSceneLogic'

const MOVED_TAB_REDIRECTS = [
    { from: '/workflows/opt-outs', to: '/audience/topics', surface: 'workflows', tab: 'opt-outs' },
    { from: '/workflows/suppression', to: '/audience/suppression', surface: 'workflows', tab: 'suppression' },
    { from: '/broadcasts/opt-outs', to: '/audience/topics', surface: 'broadcasts', tab: 'opt-outs' },
    { from: '/broadcasts/suppression', to: '/audience/suppression', surface: 'broadcasts', tab: 'suppression' },
]

function currentPath(): string {
    return removeProjectIdIfPresent(router.values.location.pathname)
}

function setAudienceFlag(enabled: boolean): void {
    featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.WORKFLOWS_AUDIENCE]: enabled })
}

describe('audience routing', () => {
    beforeEach(() => {
        initKeaTests()
        jest.spyOn(posthog, 'capture')
        featureFlagLogic.mount()
        workflowsSceneLogic().mount()
        broadcastsSceneLogic.mount()
    })

    afterEach(() => {
        jest.restoreAllMocks()
    })

    it.each(MOVED_TAB_REDIRECTS)('with the flag on, $from is replaced by $to', ({ from, to, surface, tab }) => {
        setAudienceFlag(true)

        router.actions.push(from)

        expect(currentPath()).toBe(to)
        expect(router.values.lastMethod).toBe('REPLACE')
        expect(posthog.capture).toHaveBeenCalledWith('messaging tab redirected to audience', { tab, from: surface })
    })

    it.each(MOVED_TAB_REDIRECTS)('with the flag off, $from stays put', ({ from }) => {
        setAudienceFlag(false)

        router.actions.push(from)

        expect(currentPath()).toBe(from)
        expect(posthog.capture).not.toHaveBeenCalledWith('messaging tab redirected to audience', expect.anything())
    })

    it('redirects a moved tab that opened before the flags arrived', () => {
        router.actions.push('/broadcasts/suppression')

        setAudienceFlag(true)

        expect(currentPath()).toBe('/audience/suppression')
    })

    it('leaves other tabs alone when the flags arrive', () => {
        router.actions.push('/workflows/library')

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
