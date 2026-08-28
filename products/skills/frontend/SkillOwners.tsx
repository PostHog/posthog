import { useActions, useValues } from 'kea'

import { IconPencil } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { MemberSelectMultiple } from 'lib/components/MemberSelectMultiple'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { userLogic } from 'scenes/userLogic'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { llmSkillLogic } from './llmSkillLogic'
import { SKILL_OWNER_MAX_COUNT } from './skillConstants'

/** Owners of a skill, with an inline editor. Ownership is keyed on the skill name rather than a
 * version, so this saves through the owners-only write path and never publishes a version. */
export function SkillOwners(): JSX.Element {
    const { skillOwners, ownersEditing, ownerDraft, ownerDraftChanged, savingOwners } = useValues(llmSkillLogic)
    const { openOwnersEditor, closeOwnersEditor, setOwnerDraft, saveOwners } = useActions(llmSkillLogic)
    const { user } = useValues(userLogic)

    return (
        <div data-attr="llma-skill-owners">
            <label className="text-xs font-semibold uppercase text-secondary">Owners</label>
            {ownersEditing ? (
                <div className="mt-1 flex max-w-lg flex-col gap-2">
                    <MemberSelectMultiple
                        idKey="uuid"
                        value={ownerDraft}
                        onChange={(users) => setOwnerDraft(users.map((selected) => selected.uuid))}
                    />
                    <p className="m-0 text-xs text-secondary">
                        Owners are who to ask about this skill. Saving them does not publish a new version.
                    </p>
                    <div className="flex gap-2">
                        <LemonButton
                            type="primary"
                            size="small"
                            onClick={() => saveOwners(ownerDraft)}
                            loading={savingOwners}
                            disabledReason={
                                ownerDraft.length > SKILL_OWNER_MAX_COUNT
                                    ? `A skill can have at most ${SKILL_OWNER_MAX_COUNT} owners`
                                    : !ownerDraftChanged
                                      ? 'No changes to save'
                                      : undefined
                            }
                            data-attr="llma-skill-owners-save"
                        >
                            Save
                        </LemonButton>
                        <LemonButton
                            type="secondary"
                            size="small"
                            onClick={closeOwnersEditor}
                            disabledReason={savingOwners ? 'Saving…' : undefined}
                            data-attr="llma-skill-owners-cancel"
                        >
                            Cancel
                        </LemonButton>
                    </div>
                </div>
            ) : (
                <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1">
                    {skillOwners.length > 0 ? (
                        skillOwners.map((owner) => (
                            <ProfilePicture
                                key={owner.uuid}
                                // Not the generated owner object itself: its hedgehog_config is typed
                                // as a loose record, which ProfilePicture's prop type rejects.
                                user={{
                                    first_name: owner.first_name,
                                    last_name: owner.last_name,
                                    email: owner.email,
                                }}
                                size="md"
                                showName
                            />
                        ))
                    ) : (
                        <span className="text-sm text-secondary">No owner</span>
                    )}
                    {skillOwners.length === 0 && user ? (
                        <AccessControlAction
                            resourceType={AccessControlResourceType.LlmSkill}
                            minAccessLevel={AccessControlLevel.Editor}
                        >
                            <LemonButton
                                size="xsmall"
                                type="secondary"
                                onClick={() => saveOwners([user.uuid])}
                                loading={savingOwners}
                                data-attr="llma-skill-owners-claim"
                            >
                                Claim it
                            </LemonButton>
                        </AccessControlAction>
                    ) : null}
                    <AccessControlAction
                        resourceType={AccessControlResourceType.LlmSkill}
                        minAccessLevel={AccessControlLevel.Editor}
                    >
                        <LemonButton
                            size="xsmall"
                            type="secondary"
                            icon={skillOwners.length > 0 ? <IconPencil /> : undefined}
                            onClick={openOwnersEditor}
                            data-attr="llma-skill-owners-edit"
                        >
                            {skillOwners.length > 0 ? 'Edit' : 'Pick someone else'}
                        </LemonButton>
                    </AccessControlAction>
                </div>
            )}
        </div>
    )
}
