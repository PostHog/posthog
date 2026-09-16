import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, LemonInput } from '@posthog/lemon-ui'

import { SkillPicker } from 'lib/components/SkillPicker/SkillPicker'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { teamLogic } from 'scenes/teamLogic'

import { llmSkillsResolveNameRetrieve } from 'products/skills/frontend/generated/api'

import { REVIEW_SKILL_KIND_LABELS, REVIEW_SKILL_PREFIX_BY_KIND, reviewHogSettingsLogic } from './reviewHogSettingsLogic'

/**
 * The "Use an existing skill" flow: search the team's skill store, pick a source skill, confirm
 * the copy's name, and the logic copies it under the kind's prefix and switches it on. Hosts the
 * generic SkillPicker for the search step and owns the ReviewHog-specific confirm step.
 */
export function AdoptSkillModal(): JSX.Element {
    const {
        adoptSkillKind,
        adoptSource,
        adoptSlug,
        adoptSlugError,
        adoptingSkill,
        adoptSkillGroups,
        adoptableSkillsLoading,
        blindSpots,
        validators,
        resolutionSkills,
    } = useValues(reviewHogSettingsLogic)
    const { closeAdoptSkillModal, chooseAdoptSource, backToAdoptSearch, setAdoptSlug, submitAdoptSkill } =
        useActions(reviewHogSettingsLogic)
    const { currentTeamId } = useValues(teamLogic)

    const kindLabel = adoptSkillKind ? REVIEW_SKILL_KIND_LABELS[adoptSkillKind] : ''
    // Single-active kinds swap the user's current selection on adopt; name what gets replaced.
    const replacedSkillName =
        adoptSkillKind === 'blind_spots'
            ? blindSpots?.find((s) => s.active)?.skill_name
            : adoptSkillKind === 'validator'
              ? validators?.find((s) => s.active)?.skill_name
              : adoptSkillKind === 'resolution'
                ? resolutionSkills?.find((s) => s.active)?.skill_name
                : undefined

    return (
        <LemonModal
            isOpen={adoptSkillKind !== null}
            onClose={closeAdoptSkillModal}
            // Block close while the copy/activation requests are in flight: closing mid-flight lets
            // the user reopen and adopt again, and the first request's tail then closes that modal
            // and fires a success toast naming the wrong source.
            closable={!adoptingSkill}
            title={`Use an existing skill as your ${kindLabel}`}
            description={
                adoptSource
                    ? undefined
                    : 'Pick a skill from your team. A copy of it becomes a review skill; the original stays untouched.'
            }
            width={720}
            data-attr="review-hog-adopt-skill-modal"
            footer={
                adoptSource ? (
                    <>
                        <div className="flex-1">
                            <LemonButton type="secondary" onClick={backToAdoptSearch} disabled={adoptingSkill}>
                                Back
                            </LemonButton>
                        </div>
                        <LemonButton
                            type="primary"
                            onClick={submitAdoptSkill}
                            loading={adoptingSkill}
                            disabledReason={adoptSlugError ?? undefined}
                            data-attr="review-hog-adopt-skill-submit"
                        >
                            Copy and switch on
                        </LemonButton>
                    </>
                ) : (
                    <LemonButton type="secondary" onClick={closeAdoptSkillModal}>
                        Close
                    </LemonButton>
                )
            }
        >
            {adoptSource ? (
                <div className="flex flex-col gap-4">
                    <p className="m-0 text-sm text-secondary">
                        This copies <span className="font-semibold">{adoptSource.name}</span> into a new {kindLabel}{' '}
                        skill and switches it on for your PR reviews. Edits to the original won't change the copy.
                    </p>
                    {replacedSkillName && (
                        <LemonBanner type="info">
                            It replaces <span className="font-semibold">{replacedSkillName}</span> as your active{' '}
                            {kindLabel}.
                        </LemonBanner>
                    )}
                    <LemonField.Pure label="Name of the copy" error={adoptSlugError}>
                        <LemonInput
                            prefix={
                                <span className="whitespace-nowrap text-secondary">
                                    {adoptSkillKind ? REVIEW_SKILL_PREFIX_BY_KIND[adoptSkillKind] : ''}
                                </span>
                            }
                            value={adoptSlug}
                            onChange={setAdoptSlug}
                            autoFocus
                            data-attr="review-hog-adopt-skill-slug"
                        />
                    </LemonField.Pure>
                </div>
            ) : (
                <SkillPicker
                    groups={adoptSkillGroups}
                    loading={adoptableSkillsLoading}
                    emptyMessage='Your team has no other skills to use yet. "Create your own" makes one with an agent.'
                    selectLabel="Use this skill"
                    onSelect={(skill) => chooseAdoptSource({ name: skill.name, description: skill.description })}
                    // Resolve returns the whole body; the plain name endpoint caps it at 8000 chars,
                    // which would preview an adopted skill short of what the copy actually runs.
                    loadBody={async (name) =>
                        (await llmSkillsResolveNameRetrieve(String(currentTeamId), name)).skill.body
                    }
                    data-attr="review-hog-adopt-skill-picker"
                />
            )}
        </LemonModal>
    )
}
