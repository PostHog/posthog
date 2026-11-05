import { useActions, useValues } from 'kea'

import { IconPlus, IconSearch } from '@posthog/icons'
import { LemonButton, LemonMenu, LemonSkeleton, LemonSwitch, Link } from '@posthog/lemon-ui'

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

function capitalize(text: string): string {
    return text.charAt(0).toUpperCase() + text.slice(1)
}

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
        <section className="@container flex flex-col overflow-hidden rounded border border-primary bg-surface-primary">
            <header className="flex flex-wrap items-start justify-between gap-x-4 gap-y-1 px-4 py-3">
                <div className="flex max-w-160 min-w-0 flex-col gap-1">
                    <div className="flex flex-wrap items-center gap-2">
                        <h3 className="m-0 text-base font-semibold">Review skills</h3>
                    </div>
                    <p className="m-0 text-xs text-secondary">
                        Choose what your Deep reviews check. Editing skill text changes it for the whole project.
                    </p>
                </div>
                <span className="text-xs text-secondary">Last 10 Deep reviews</span>
            </header>
            <div className="hidden grid-cols-[minmax(0,1fr)_minmax(0,16rem)] gap-3 border-t border-primary px-4 py-1.5 text-xxs font-semibold uppercase tracking-wide text-secondary @min-[48rem]:grid">
                <span>Skill</span>
                <span>My preference</span>
            </div>

            <SkillGroupHeader title="Perspectives" rule="Choose at least one" />
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
                note="Used when you allow fix commits"
                skills={resolutionSkills}
                onSelect={selectResolutionSkill}
                dataAttr="review-hog-resolution-mine"
            />

            <footer className="flex flex-wrap items-center gap-2 border-t border-primary px-4 py-3">
                <LemonMenu
                    items={SKILL_KINDS.map((kind) => ({
                        label: capitalize(REVIEW_SKILL_KIND_LABELS[kind]),
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
                        label: capitalize(REVIEW_SKILL_KIND_LABELS[kind]),
                        onClick: () => openAdoptSkillModal(kind),
                        'data-attr': `review-hog-adopt-skill-${kind}`,
                    }))}
                >
                    <LemonButton type="secondary" size="small" icon={<IconSearch />} data-attr="review-hog-adopt-skill">
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
        </section>
    )
}
