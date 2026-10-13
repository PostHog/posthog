import { useActions, useValues } from 'kea'

import { IconPlus, IconSearch } from '@posthog/icons'
import { LemonButton, LemonMenu, LemonSkeleton, LemonSwitch, Link } from '@posthog/lemon-ui'

import { LemonCard } from 'lib/lemon-ui/LemonCard'
import { capitalizeFirstLetter } from 'lib/utils/strings'

import { SceneSection } from '~/layout/scenes/components/SceneSection'

import {
    REVIEW_SKILL_KIND_LABELS,
    ReviewSkillKind,
    reviewHogSettingsLogic,
} from 'products/review_hog/frontend/reviewHogSettingsLogic'
import { prettifySkillName } from 'products/review_hog/frontend/skillNames'

import { SingleActiveSkillGroup } from './SingleActiveSkillGroup'
import { SkillGroupHeader } from './SkillGroupHeader'
import { SkillKept, SkillRow } from './SkillRow'

const SKILL_KINDS: ReviewSkillKind[] = ['perspective', 'blind_spots', 'validator', 'resolution']

/**
 * The viewer's review skills for the Deep reviews they start, always open. Kept counts come from the
 * viewer's own last Deep reviews, never from the Activity tab's Mine / Everyone switch.
 */
export function ReviewSkillsPanel(): JSX.Element {
    const {
        perspectives,
        blindSpots,
        validators,
        resolutionSkills,
        deepSkillKept,
        deepValidationKept,
        savingSkillNames,
        creatingSkillKind,
    } = useValues(reviewHogSettingsLogic)
    const {
        togglePerspective,
        selectBlindSpots,
        selectValidator,
        selectResolutionSkill,
        startSkillAuthorTask,
        openAdoptSkillModal,
        openPipelineDetail,
    } = useActions(reviewHogSettingsLogic)

    const keptFor = (skillName: string): SkillKept | null => deepSkillKept?.[skillName] ?? null
    const enabledCount = perspectives?.filter((perspective) => perspective.enabled).length ?? 0
    const validationKept: SkillKept | null = deepValidationKept
        ? { kept: deepValidationKept.kept, raised: deepValidationKept.judged }
        : null

    return (
        <SceneSection
            title="Deep review skills"
            description="Skills decide what a Deep review looks for and what it posts."
            titleHelper="Standard reviews use a fixed set of skills and read none of these."
            actions={<span className="text-xs text-secondary">Kept counts: your last 10 Deep reviews</span>}
        >
            <LemonCard hoverEffect={false} className="flex flex-col overflow-hidden p-0">
                <SkillGroupHeader title="Perspectives" rule="any number, at least one" />
                {perspectives === null ? (
                    <div className="px-4 py-2">
                        <LemonSkeleton className="h-12 w-full" />
                    </div>
                ) : (
                    perspectives.map((perspective) => (
                        <SkillRow
                            key={perspective.skill_name}
                            skillName={perspective.skill_name}
                            description={perspective.description}
                            kept={deepSkillKept === null ? undefined : keptFor(perspective.skill_name)}
                            mine={
                                <LemonSwitch
                                    aria-label={`Mine: ${prettifySkillName(perspective.skill_name)}`}
                                    checked={perspective.enabled}
                                    onChange={(checked) => togglePerspective(perspective.skill_name, checked)}
                                    disabledReason={
                                        savingSkillNames.includes(perspective.skill_name)
                                            ? 'Saving…'
                                            : perspective.enabled && enabledCount <= 1
                                              ? 'Keep at least one perspective on'
                                              : undefined
                                    }
                                    data-attr="review-hog-perspective-mine"
                                />
                            }
                        />
                    ))
                )}

                <SingleActiveSkillGroup
                    title="Blind-spot check"
                    skills={blindSpots}
                    keptFor={deepSkillKept === null ? undefined : keptFor}
                    onSelect={selectBlindSpots}
                    dataAttr="review-hog-blind-spots-mine"
                />
                <SingleActiveSkillGroup
                    title="Validation criteria"
                    skills={validators}
                    keptFor={deepSkillKept === null ? undefined : () => validationKept}
                    onSelect={selectValidator}
                    dataAttr="review-hog-validator-mine"
                />
                <SingleActiveSkillGroup
                    title="Resolution criteria"
                    note="only when Resolve is on"
                    skills={resolutionSkills}
                    onSelect={selectResolutionSkill}
                    dataAttr="review-hog-resolution-mine"
                />

                <footer className="flex flex-wrap items-center gap-2 border-t border-primary px-4 py-3">
                    <LemonMenu
                        items={SKILL_KINDS.map((kind) => ({
                            label: capitalizeFirstLetter(REVIEW_SKILL_KIND_LABELS[kind]),
                            onClick: () => startSkillAuthorTask(kind),
                        }))}
                    >
                        <LemonButton
                            type="secondary"
                            size="small"
                            icon={<IconPlus />}
                            loading={creatingSkillKind !== null}
                            data-attr="review-hog-new-skill"
                        >
                            New skill
                        </LemonButton>
                    </LemonMenu>
                    <LemonMenu
                        items={SKILL_KINDS.map((kind) => ({
                            label: capitalizeFirstLetter(REVIEW_SKILL_KIND_LABELS[kind]),
                            onClick: () => openAdoptSkillModal(kind),
                            'data-attr': `review-hog-adopt-skill-${kind}`,
                        }))}
                    >
                        <LemonButton
                            type="secondary"
                            size="small"
                            icon={<IconSearch />}
                            data-attr="review-hog-adopt-skill"
                        >
                            Use an existing skill
                        </LemonButton>
                    </LemonMenu>
                    <Link
                        className="text-xs"
                        onClick={() => openPipelineDetail()}
                        data-attr="review-hog-skills-pipeline-detail"
                    >
                        How a review uses skills
                    </Link>
                </footer>
            </LemonCard>
        </SceneSection>
    )
}
