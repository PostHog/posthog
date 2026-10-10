import { useValues } from 'kea'

import { LemonSelect, LemonSkeleton } from '@posthog/lemon-ui'

import { reviewHogSettingsLogic } from 'products/review_hog/frontend/reviewHogSettingsLogic'
import { prettifySkillName } from 'products/review_hog/frontend/skillNames'

import { SkillGroupHeader } from './SkillGroupHeader'
import { SkillRow } from './SkillRow'

interface SingleActiveSkill {
    skill_name: string
    description: string
    active: boolean
}

/** A kind of skill where one runs: the active skill's row, with a select to switch to another. */
export function SingleActiveSkillGroup({
    title,
    note,
    skills,
    onSelect,
    dataAttr,
}: {
    title: string
    note?: string
    skills: SingleActiveSkill[] | null
    onSelect: (skillName: string) => void
    dataAttr: string
}): JSX.Element {
    const { savingSkillNames } = useValues(reviewHogSettingsLogic)
    const active = skills?.find((skill) => skill.active) ?? null
    const saving = !!skills?.some((skill) => savingSkillNames.includes(skill.skill_name))

    const select = skills?.length ? (
        <LemonSelect
            size="small"
            aria-label={`Mine: ${title}`}
            value={active?.skill_name ?? null}
            placeholder="Pick a skill"
            options={skills.map((skill) => ({
                value: skill.skill_name,
                label: prettifySkillName(skill.skill_name),
            }))}
            onChange={(skillName) => skillName && skillName !== active?.skill_name && onSelect(skillName)}
            disabledReason={saving ? 'Saving…' : undefined}
            className="max-w-full"
            data-attr={dataAttr}
        />
    ) : null

    return (
        <>
            <SkillGroupHeader title={title} rule="one runs" note={note} />
            {skills === null ? (
                <div className="px-4 py-2">
                    <LemonSkeleton className="h-12 w-full" />
                </div>
            ) : select === null ? (
                <span className="px-4 py-2 text-xs text-secondary">No skill of this kind yet.</span>
            ) : active === null ? (
                // An archived skill leaves the rest inactive and the review falls back to the built-in skill,
                // so the select must stay reachable.
                <div className="flex flex-wrap items-center justify-between gap-2 px-4 py-2">
                    <span className="text-xs text-secondary">None selected, so the built-in default runs.</span>
                    {select}
                </div>
            ) : (
                <SkillRow skillName={active.skill_name} description={active.description} mine={select} />
            )}
        </>
    )
}
