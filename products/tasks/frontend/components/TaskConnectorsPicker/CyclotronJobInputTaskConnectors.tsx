import { useValues } from 'kea'

import { LemonInputSelect, LemonTag } from '@posthog/lemon-ui'

import type { CustomInputRendererProps } from 'lib/components/CyclotronJob/customInputRenderers'

import { taskConnectorsPickerLogic } from './taskConnectorsPickerLogic'

export default function CyclotronJobInputTaskConnectors({ value, onChange }: CustomInputRendererProps): JSX.Element {
    const { installations, installationsLoading } = useValues(taskConnectorsPickerLogic)

    const selectedIds: string[] = Array.isArray(value) ? value : []
    const enabledInstallations = installations.filter((installation) => installation.is_enabled !== false)

    const options = enabledInstallations.map((installation) => {
        const label = installation.display_name || installation.name
        return {
            key: installation.id,
            label,
            labelComponent: installation.needs_reauth ? (
                <span className="inline-flex items-center gap-1.5">
                    {label}
                    <LemonTag type="warning">Needs reauthorization</LemonTag>
                </span>
            ) : undefined,
        }
    })
    // Stored ids whose installation has since been removed or disabled still need to render,
    // so the person editing can see and remove them.
    for (const id of selectedIds) {
        if (!options.some((option) => option.key === id)) {
            options.push({ key: id, label: `Unavailable connector (${id})`, labelComponent: undefined })
        }
    }

    return (
        <LemonInputSelect
            mode="multiple"
            value={selectedIds}
            onChange={(ids) => onChange(ids)}
            options={options}
            loading={installationsLoading}
            placeholder="No connectors"
            data-attr="task-connectors-picker"
        />
    )
}
