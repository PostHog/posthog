import type { CSSProperties } from 'react'

import { Checkbox, Field } from '@posthog/quill'

import { QuillChartOptionLabel } from 'lib/components/ChartOptions/QuillChartOptionLabel'
import { capitalizeFirstLetter } from 'lib/utils/strings'

import { LifecycleToggle } from '~/types'

export interface LifecycleToggleRow {
    name: LifecycleToggle
    color: string
    tooltip: string
    checked: boolean
}

export interface QuillLifecycleTogglesProps {
    rows: LifecycleToggleRow[]
    onToggle: (name: LifecycleToggle) => void
}

export function QuillLifecycleToggles({ rows, onToggle }: QuillLifecycleTogglesProps): JSX.Element {
    return (
        <div className="flex flex-col gap-2">
            {rows.map(({ name, color, tooltip, checked }) => (
                <Field key={name} orientation="horizontal" className="gap-2">
                    <Checkbox
                        id={`lifecycle-toggle-${name}`}
                        checked={checked}
                        onCheckedChange={() => onToggle(name)}
                        // The checkbox takes the lifecycle's chart color, so it doubles as the legend.
                        style={{ '--primary': color } as CSSProperties}
                    />
                    <QuillChartOptionLabel
                        htmlFor={`lifecycle-toggle-${name}`}
                        label={capitalizeFirstLetter(name)}
                        info={tooltip}
                    />
                </Field>
            ))}
        </div>
    )
}
