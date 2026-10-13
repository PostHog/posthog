import { useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
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
}): JSX.Element {
    const { publishingSkills } = useValues(llmSkillsLogic)
    const { user } = useValues(userLogic)

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
