import { IconPlus, IconTrash } from '@posthog/icons'
import { LemonButton, LemonInput } from '@posthog/lemon-ui'

import { MetricsAlertLabel } from './metricsAlertUtils'

interface MetricsAlertLabelsFieldProps {
    value?: MetricsAlertLabel[]
    onChange?: (labels: MetricsAlertLabel[]) => void
}

export function MetricsAlertLabelsField({ value = [], onChange }: MetricsAlertLabelsFieldProps): JSX.Element {
    const update = (index: number, change: Partial<MetricsAlertLabel>): void => {
        onChange?.(value.map((label, i) => (i === index ? { ...label, ...change } : label)))
    }

    return (
        <div className="flex flex-col gap-2">
            {value.map((label, index) => (
                <div key={index} className="flex items-center gap-2">
                    <LemonInput
                        className="flex-1 min-w-0"
                        placeholder="Name, such as team"
                        value={label.name}
                        onChange={(name) => update(index, { name })}
                        size="small"
                        data-attr="metrics-alert-label-name"
                    />
                    <span className="font-mono text-secondary">=</span>
                    <LemonInput
                        className="flex-1 min-w-0"
                        placeholder="Value, such as checkout"
                        value={label.value}
                        onChange={(labelValue) => update(index, { value: labelValue })}
                        size="small"
                        data-attr="metrics-alert-label-value"
                    />
                    <LemonButton
                        icon={<IconTrash />}
                        size="small"
                        tooltip="Remove label"
                        onClick={() => onChange?.(value.filter((_, i) => i !== index))}
                        data-attr="metrics-alert-label-remove"
                    />
                </div>
            ))}
            <div>
                <LemonButton
                    type="secondary"
                    size="small"
                    icon={<IconPlus />}
                    onClick={() => onChange?.([...value, { name: '', value: '' }])}
                    data-attr="metrics-alert-label-add"
                >
                    Add label
                </LemonButton>
            </div>
        </div>
    )
}
