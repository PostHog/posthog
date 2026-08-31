import { useValues } from 'kea'

import { LemonInputSelect } from '@posthog/lemon-ui'

import type { CustomInputRendererProps } from 'lib/components/CyclotronJob/customInputRenderers'

import { taskSkillsPickerLogic } from './taskSkillsPickerLogic'

export default function CyclotronJobInputTaskSkills({ value, onChange }: CustomInputRendererProps): JSX.Element {
    const { skills, skillsLoading } = useValues(taskSkillsPickerLogic)

    const selectedNames: string[] = Array.isArray(value) ? value : []

    const options = skills.map((skill) => ({ key: skill.name, label: skill.name }))
    // A stored name whose skill has since been archived still needs to render, so the person
    // editing can see and remove it.
    for (const name of selectedNames) {
        if (!options.some((option) => option.key === name)) {
            options.push({ key: name, label: `Unavailable skill (${name})` })
        }
    }

    return (
        <LemonInputSelect
            mode="multiple"
            value={selectedNames}
            onChange={(names) => onChange(names)}
            options={options}
            loading={skillsLoading}
            placeholder="No skills"
            data-attr="task-skills-picker"
        />
    )
}
