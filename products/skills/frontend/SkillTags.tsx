import { useActions, useValues } from 'kea'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { ObjectTags } from 'lib/components/ObjectTags/ObjectTags'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { llmSkillLogic } from './llmSkillLogic'
import { skillTagsModel } from './skillTagsModel'

/** Tags on a skill, with an inline editor. Tags are keyed on the skill name rather than a version,
 * so this saves through the tags-only write path and never publishes a version. */
export function SkillTags(): JSX.Element {
    const { skillTags, savingTags } = useValues(llmSkillLogic)
    const { saveTags } = useActions(llmSkillLogic)
    const { availableTags } = useValues(skillTagsModel)

    return (
        <div data-attr="llma-skill-tags">
            <label className="text-xs font-semibold uppercase text-secondary">Tags</label>
            <div className="mt-1">
                <AccessControlAction
                    resourceType={AccessControlResourceType.LlmSkill}
                    minAccessLevel={AccessControlLevel.Editor}
                >
                    {({ disabledReason }) =>
                        disabledReason ? (
                            <ObjectTags tags={[...skillTags]} staticOnly />
                        ) : (
                            <ObjectTags
                                tags={[...skillTags]}
                                tagsAvailable={availableTags}
                                saving={savingTags}
                                onChange={saveTags}
                                inputPlaceholder='try "growth"'
                            />
                        )
                    }
                </AccessControlAction>
            </div>
            <p className="mt-1 mb-0 text-xs text-secondary">
                Tags group skills on the list page. Saving them does not publish a new version.
            </p>
        </div>
    )
}
