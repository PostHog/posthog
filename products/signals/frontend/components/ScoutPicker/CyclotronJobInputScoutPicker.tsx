import { useValues } from 'kea'

import { LemonInputSelect, LemonInputSelectOption } from '@posthog/lemon-ui'

import type { CustomInputRendererProps } from 'lib/components/CyclotronJob/customInputRenderers'

import { prettifyScoutSkillName } from 'products/signals/frontend/inbox/utils/scoutRunsWindow'

import { scoutPickerLogic } from './scoutPickerLogic'

export default function CyclotronJobInputScoutPicker({ value, onChange }: CustomInputRendererProps): JSX.Element {
    const { scoutConfigs, scoutConfigsLoading } = useValues(scoutPickerLogic)

    const selected = typeof value === 'string' ? value : ''
    const options: LemonInputSelectOption[] = scoutConfigs.map((config) => ({
        key: config.skill_name,
        label: config.enabled
            ? prettifyScoutSkillName(config.skill_name)
            : `${prettifyScoutSkillName(config.skill_name)} (paused)`,
    }))
    // A stored skill name that isn't in this team's fleet (deleted since, or authored
    // elsewhere) still needs to render as itself, not as blank.
    if (selected && !options.some((option) => option.key === selected)) {
        options.push({ key: selected, label: selected })
    }

    return (
        <LemonInputSelect
            mode="single"
            data-attr="select-signals-scout"
            placeholder={scoutConfigsLoading ? 'Loading scouts...' : 'Select a scout...'}
            value={selected ? [selected] : []}
            onChange={(val) => onChange(val[0] ?? null)}
            options={options}
            loading={scoutConfigsLoading}
        />
    )
}
