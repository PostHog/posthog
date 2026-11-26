import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { initKeaTests } from '~/test/init'

import { isRequestAllowlistVisible } from './isRequestAllowlistVisible'

describe('isRequestAllowlistVisible', () => {
    it.each([
        ['the flag is on', true, {}, true],
        ['the flag is off and the lists are empty', false, { allowed_hosts: [], allowed_ips: [] }, false],
        ['the flag is off and a domain is saved', false, { allowed_hosts: ['example.com'] }, true],
        ['the flag is off and an IP address is saved', false, { allowed_ips: ['203.0.113.7'] }, true],
    ])('when %s', (_, flagOn, lists, visible) => {
        initKeaTests()
        featureFlagLogic.mount()
        const flag = FEATURE_FLAGS.FEATURE_FLAG_REQUEST_ALLOWLIST
        featureFlagLogic.actions.setFeatureFlags([flag], { [flag]: flagOn })

        const team = { ...MOCK_DEFAULT_TEAM, feature_flag_policy_config: { require_tags: false, ...lists } }

        expect(isRequestAllowlistVisible(team)).toBe(visible)
    })
})
