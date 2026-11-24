import { router } from 'kea-router'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import type { ErrorTrackingQuery } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { issueQueryOptionsLogic } from '../../components/IssueQueryOptions/issueQueryOptionsLogic'
import { ERROR_TRACKING_SCENE_LOGIC_KEY, errorTrackingSceneLogic } from './errorTrackingSceneLogic'

describe('errorTrackingSceneLogic', () => {
    it('restores the active tab from the canonical error-tracking url', () => {
        initKeaTests()
        const logic = errorTrackingSceneLogic()
        logic.mount()

        router.actions.push('/error-tracking', { activeTab: 'configuration' })

        expect(logic.values.activeTab).toBe('configuration')
    })

    // The filter control is hidden while issue tags are off, so a tag filter from a link would narrow the list with
    // nothing on screen to clear it.
    it.each([
        [false, undefined],
        [true, { has: ['cause_in_trace'], hasNot: [] }],
    ])('with issue tags on %p, sends the tag filter %p', (issueTagsOn, expected) => {
        initKeaTests()
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.ERROR_TRACKING_ISSUE_TAGS]: issueTagsOn })
        const logic = errorTrackingSceneLogic()
        logic.mount()

        issueQueryOptionsLogic({ logicKey: ERROR_TRACKING_SCENE_LOGIC_KEY }).actions.setIssueTagState(
            'cause_in_trace',
            'has'
        )

        expect((logic.values.query.source as ErrorTrackingQuery).issueTags).toEqual(expected)
    })
})
