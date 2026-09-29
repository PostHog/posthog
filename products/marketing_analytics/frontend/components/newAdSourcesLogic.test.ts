import { MOCK_DEFAULT_USER } from 'lib/api.mock'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { userLogic } from 'scenes/userLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { expectLogic } from '~/test/keaTestUtils'

import { NEW_AD_SOURCES_SEEN_KEY, newAdSourcesLogic } from './newAdSourcesLogic'

describe('newAdSourcesLogic', () => {
    beforeEach(() => {
        initKeaTests()
        featureFlagLogic.mount()
        userLogic.mount()
        newAdSourcesLogic.mount()
    })

    it.each([
        ['an enabled source', true, {}, true, true],
        ['disabled sources', false, {}, true, false],
        ['a non-boolean flag', 'control', {}, true, false],
        ['an existing dismissal', true, { [NEW_AD_SOURCES_SEEN_KEY]: true }, true, false],
        ['a user still loading', true, {}, false, false],
    ])('only announces available sources for %s', (_label, flag, seen, loaded, expected) => {
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.MARKETING_ANALYTICS_APPLE_ADS]: flag })
        userLogic.actions.loadUserSuccess(loaded ? { ...MOCK_DEFAULT_USER, has_seen_product_intro_for: seen } : null)
        expect(newAdSourcesLogic.values.showNotice).toBe(expected)
        expect(newAdSourcesLogic.values.newSources).toEqual(flag === true ? ['AppleSearchAds'] : [])
    })

    it('hides the shared notice immediately and remembers dismissal on remount', async () => {
        let saved = false
        useMocks({
            patch: {
                '/api/users/@me/product_intro_seen': async ({ request }) => {
                    expect(await request.json()).toEqual({ product_key: NEW_AD_SOURCES_SEEN_KEY, seen: true })
                    saved = true
                    return [200, { [NEW_AD_SOURCES_SEEN_KEY]: true }]
                },
            },
            get: {
                '/api/users/@me/': () => [
                    200,
                    { ...MOCK_DEFAULT_USER, has_seen_product_intro_for: { [NEW_AD_SOURCES_SEEN_KEY]: saved } },
                ],
            },
        })
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.MARKETING_ANALYTICS_APPLE_ADS]: true })
        userLogic.actions.loadUserSuccess({ ...MOCK_DEFAULT_USER, has_seen_product_intro_for: {} })
        const finish = expectLogic(newAdSourcesLogic, () =>
            newAdSourcesLogic.actions.dismissNotice()
        ).toFinishAllListeners()
        expect(newAdSourcesLogic.values.showNotice).toBe(false)
        await finish
        expect(saved).toBe(true)
        newAdSourcesLogic.unmount()
        newAdSourcesLogic.mount()
        expect(newAdSourcesLogic.values.showNotice).toBe(false)
    })
})
