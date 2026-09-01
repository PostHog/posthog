import { useActions, useValues } from 'kea'

import { LemonInputSelect } from '@posthog/lemon-ui'

import type { CustomInputRendererProps } from 'lib/components/CyclotronJob/customInputRenderers'

import { MAX_ATTACHED_SKILLS, taskSkillsPickerLogic } from './taskSkillsPickerLogic'

export default function CyclotronJobInputTaskSkills({ value, onChange }: CustomInputRendererProps): JSX.Element {
    const { skillOptions, skillOptionsLoading, skillCount, hasMoreSkills, search } = useValues(taskSkillsPickerLogic)
    const { ensureOptionsLoaded, setSearch, loadOptions } = useActions(taskSkillsPickerLogic)

    const selectedNames: string[] = Array.isArray(value) ? value : []

    const options = skillOptions.map((skill) => ({
        key: skill.name,
        label: skill.name,
        // Stacked, so a long name and a long description each truncate on their own line
        // instead of fighting for one row in a narrow panel.
        labelComponent: (
            <span className="flex flex-col">
                <span className="truncate">{skill.name}</span>
                {skill.description ? <span className="text-muted text-xs truncate">{skill.description}</span> : null}
            </span>
        ),
    }))
    // A selected name that is not on the loaded page renders as itself. With server-side paging
    // and a live search query, "not loaded" is the common reason a name is missing, so labeling
    // it unavailable would be wrong most of the time. The name is also the identity the run
    // resolves, so nothing is hidden by showing it plainly.
    for (const name of selectedNames) {
        if (!options.some((option) => option.key === name)) {
            options.push({ key: name, label: name, labelComponent: <span className="truncate">{name}</span> })
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
            onFocus={ensureOptionsLoaded}
            onInputChange={setSearch}
            title={hasMoreSkills ? `Showing ${skillOptions.length} of ${skillCount} skills` : undefined}
            action={
                hasMoreSkills
                    ? { children: <>Load more skills</>, onClick: () => loadOptions({ append: true }) }
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
