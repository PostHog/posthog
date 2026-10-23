import { IconTrash } from '@posthog/icons'
import { LemonButton, LemonInputSelect, LemonSelect } from '@posthog/lemon-ui'

import type { AdmissionRuleFieldApi } from 'products/signals/frontend/generated/api.schemas'

import {
    AdmissionFilterRow,
    admissionFieldDisplay,
    emptyAdmissionFilterRow,
    operatorLabel,
    operatorsForKind,
} from '../../admissionRules'

export function SourceAdmissionFilterRow({
    row,
    fields,
    error,
    disabled,
    onChange,
    onRemove,
}: {
    row: AdmissionFilterRow
    fields: AdmissionRuleFieldApi[]
    error?: string
    disabled: boolean
    onChange: (row: AdmissionFilterRow) => void
    onRemove: () => void
}): JSX.Element {
    const field = fields.find((f) => f.field === row.field) ?? fields[0]
    const display = admissionFieldDisplay(row.field)
    return (
        <div className="flex flex-col gap-1">
            <div className="flex flex-wrap items-start gap-2">
                <LemonSelect
                    size="small"
                    value={row.field}
                    options={fields.map((f) => ({ value: f.field, label: admissionFieldDisplay(f.field).label }))}
                    onChange={(value) => {
                        const next = fields.find((f) => f.field === value)
                        if (next) {
                            onChange(emptyAdmissionFilterRow(next))
                        }
                    }}
                    disabledReason={disabled ? 'Saving' : undefined}
                    data-attr="signal-source-admission-filter-field"
                />
                <LemonSelect
                    size="small"
                    value={row.operator}
                    options={operatorsForKind(field.kind).map((operator) => ({
                        value: operator,
                        label: operatorLabel(operator),
                    }))}
                    onChange={(operator) => onChange({ ...row, operator })}
                    disabledReason={disabled ? 'Saving' : undefined}
                />
                <div className="min-w-48 flex-1">
                    <LemonInputSelect
                        mode="multiple"
                        size="small"
                        value={row.values}
                        onChange={(values) => onChange({ ...row, values })}
                        options={(display.options ?? []).map((option) => ({ key: option.value, label: option.label }))}
                        allowCustomValues={!display.options}
                        placeholder={display.placeholder ?? 'Pick values'}
                        disabled={disabled}
                        aria-label={`${display.label} values`}
                    />
                </div>
                <LemonButton
                    size="small"
                    icon={<IconTrash />}
                    onClick={onRemove}
                    tooltip="Remove filter"
                    aria-label="Remove filter"
                    disabledReason={disabled ? 'Saving' : undefined}
                />
            </div>
            {error && <span className="text-xs text-danger">{error}</span>}
        </div>
    )
}
