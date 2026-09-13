import { useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { userLogic } from 'scenes/userLogic'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import type { LLMSkillListApi } from './generated/api.schemas'
import { llmSkillsLogic } from './llmSkillsLogic'
import { publishToCommunityDisabledReason } from './skillSceneComponents'

export function ShareSkillMenuItem({
    skill,
    onShare,
}: {
    skill: LLMSkillListApi
    onShare: (skill: LLMSkillListApi) => void
}): JSX.Element | null {
    const { featureFlags } = useValues(featureFlagLogic)
    const { publishingSkills } = useValues(llmSkillsLogic)
    const { user } = useValues(userLogic)

    if (!featureFlags[FEATURE_FLAGS.LLM_ANALYTICS_COMMUNITY_SKILLS]) {
        return null
    }

    return (
        <AccessControlAction
            resourceType={AccessControlResourceType.LlmSkill}
            minAccessLevel={AccessControlLevel.Editor}
        >
            <LemonButton
                onClick={() => onShare(skill)}
                disabledReason={publishToCommunityDisabledReason({
                    ownerUuids: skill.owners.map((owner) => owner.uuid),
                    currentUserUuid: user?.uuid,
                    publishing: !!publishingSkills[skill.name],
                })}
                data-attr="llma-skill-dropdown-publish-community"
                fullWidth
            >
                Publish to PostHog community…
            </LemonButton>
        </AccessControlAction>
    )
}
