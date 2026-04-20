import { IconChevronDown } from '@posthog/icons'
import { LemonButton, LemonCheckbox, LemonDropdown } from '@posthog/lemon-ui'

import { LogMessage } from '~/queries/schema/schema-general'

const SEVERITY_OPTIONS: { key: LogMessage['severity_text']; label: string }[] = [
    { key: 'trace', label: 'Trace' },
    { key: 'debug', label: 'Debug' },
    { key: 'info', label: 'Info' },
    { key: 'warn', label: 'Warn' },
    { key: 'error', label: 'Error' },
    { key: 'fatal', label: 'Fatal' },
]

interface SeverityLevelsFilterProps {
    value: LogMessage['severity_text'][]
    onChange: (levels: LogMessage['severity_text'][]) => void
}

export const SeverityLevelsFilter = ({ value, onChange }: SeverityLevelsFilterProps): JSX.Element => {
    return (
        <LemonDropdown
            closeOnClickInside={false}
            overlay={
                <div className="space-y-px p-1">
                    {SEVERITY_OPTIONS.map((option) => (
                        <LemonButton
                            key={option.key}
                            type="tertiary"
                            size="small"
                            fullWidth
                            icon={
                                <LemonCheckbox checked={value.includes(option.key)} className="pointer-events-none" />
                            }
                            onClick={() => {
                                const newLevels = value.includes(option.key)
                                    ? value.filter((l) => l !== option.key)
                                    : [...value, option.key]
                                onChange(newLevels)
                            }}
                            data-attr={`logs-severity-option-${option.key}`}
                        >
                            {option.label}
                        </LemonButton>
                    ))}
                </div>
            }
        >
            <LemonButton data-attr="logs-severity-filter" type="secondary" size="small" sideIcon={<IconChevronDown />}>
                {value.length === 0 || value.length === SEVERITY_OPTIONS.length
                    ? 'All levels'
                    : value.length === 1
                      ? (SEVERITY_OPTIONS.find((o) => o.key === value[0])?.label ?? value[0])
                      : `${value.length} levels`}
            </LemonButton>
        </LemonDropdown>
    )
}
