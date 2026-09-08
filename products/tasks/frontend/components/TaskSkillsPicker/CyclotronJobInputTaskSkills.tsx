import { useActions, useValues } from 'kea'

import { LemonInputSelect } from '@posthog/lemon-ui'

import type { CustomInputRendererProps } from 'lib/components/CyclotronJob/customInputRenderers'

import { MAX_ATTACHED_SKILLS, taskSkillsPickerLogic } from './taskSkillsPickerLogic'

export default function CyclotronJobInputTaskSkills({ value, onChange }: CustomInputRendererProps): JSX.Element {
    const { skillOptions, skillOptionsLoading, skillCount, hasMoreSkills, search } = useValues(taskSkillsPickerLogic)
    const { ensureOptionsLoaded, setSearch, loadNextPage } = useActions(taskSkillsPickerLogic)

    const selectedNames: string[] = Array.isArray(value) ? value : []

    // The description goes in the tooltip rather than the row, because LemonInputSelect renders
    // the same node for a dropdown row and for the snack of a selected value. Inlining it made
    // each selected skill a two-line snack, and only after the dropdown had loaded its options,
    // so the field grew and changed shape mid-edit. Search still matches descriptions server-side.
    const options = skillOptions.map((skill) => ({
        key: skill.name,
        label: skill.name,
        tooltip: skill.description || undefined,
    }))
    // Every selected name needs an option, including one the current page or search does not
    // cover. Without it LemonInputSelect reads the value as a custom entry and offers it back as
    // `Add "error-triage"`, which reads as though the skill were not already attached. The cost is
    // that a search cannot hide a selected skill, which is the better half of the trade: the rows
    // stay available to deselect while the query narrows everything else.
    for (const name of selectedNames) {
        if (!options.some((option) => option.key === name)) {
            options.push({ key: name, label: name, tooltip: undefined })
        }
    }

    return (
        <LemonInputSelect
            mode="multiple"
            value={selectedNames}
            onChange={(names) => onChange(names)}
            options={options}
            loading={skillOptionsLoading}
            limit={MAX_ATTACHED_SKILLS}
            // The server already applied `search`; re-filtering here would hide matches whose
            // description matched but whose name did not.
            disableFiltering
            virtualized
            onFocus={ensureOptionsLoaded}
            onInputChange={setSearch}
            title={hasMoreSkills ? `Showing ${skillOptions.length} of ${skillCount} skills` : undefined}
            action={
                hasMoreSkills && !skillOptionsLoading
                    ? { children: <>Load more skills</>, onClick: loadNextPage }
                    : undefined
            }
            emptyStateComponent={
                <p className="text-secondary italic p-1">
                    {search ? `No skills matching "${search}"` : 'No skills yet. Create one under Skills.'}
                </p>
            }
            placeholder="No skills"
            data-attr="task-skills-picker"
        />
    )
}
