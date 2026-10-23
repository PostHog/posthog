import type { AdmissionRuleFieldApi } from 'products/signals/frontend/generated/api.schemas'

// Mirrors ADMISSION_RULES_KEY and the rule tree shape in products/signals/backend/contracts.py.
export const SOURCE_ADMISSION_RULES_KEY = 'admission_rules'

export type AdmissionMatch = 'AND' | 'OR'
export type AdmissionListOperator = 'any' | 'all' | 'none'
// The form offers only the list forms of the scalar operators. `eq x` reads the same as `in [x]`.
export type AdmissionScalarOperator = 'in' | 'not_in'
export type AdmissionFormOperator = AdmissionListOperator | AdmissionScalarOperator

export interface AdmissionFilterRow {
    field: string
    operator: AdmissionFormOperator
    values: string[]
}

export interface AdmissionFiltersFormValues {
    match: AdmissionMatch
    rows: AdmissionFilterRow[]
}

interface StoredRule {
    field: string
    operator: string
    value: string | number | (string | number)[]
}

interface StoredGroup {
    operator: AdmissionMatch
    rules: (StoredRule | StoredGroup)[]
}

export interface AdmissionFieldDisplay {
    label: string
    /** Fixed choices, value to label. Free text when absent. */
    options?: { value: string; label: string }[]
    placeholder?: string
}

const FIELD_DISPLAY: Record<string, AdmissionFieldDisplay> = {
    labels: { label: 'Labels', placeholder: 'Type a label name and press Enter' },
    priority: {
        label: 'Priority',
        options: [
            { value: '0', label: 'No priority' },
            { value: '1', label: 'Urgent' },
            { value: '2', label: 'High' },
            { value: '3', label: 'Medium' },
            { value: '4', label: 'Low' },
        ],
    },
    state_name: { label: 'Status', placeholder: 'Type a status name and press Enter' },
    state_type: {
        label: 'Status type',
        options: [
            { value: 'triage', label: 'Triage' },
            { value: 'backlog', label: 'Backlog' },
            { value: 'unstarted', label: 'Unstarted' },
            { value: 'started', label: 'Started' },
        ],
    },
    state: { label: 'State', placeholder: 'Type a state and press Enter' },
}

export function admissionFieldDisplay(field: string): AdmissionFieldDisplay {
    const known = FIELD_DISPLAY[field]
    if (known) {
        return known
    }
    const words = field.replace(/_/g, ' ')
    return { label: words.charAt(0).toUpperCase() + words.slice(1), placeholder: 'Type a value and press Enter' }
}

export const LIST_OPERATOR_LABELS: Record<AdmissionListOperator, string> = {
    any: 'has any of',
    all: 'has all of',
    none: 'has none of',
}

export const SCALAR_OPERATOR_LABELS: Record<AdmissionScalarOperator, string> = {
    in: 'is any of',
    not_in: 'is none of',
}

export function operatorsForKind(kind: AdmissionRuleFieldApi['kind']): AdmissionFormOperator[] {
    return kind === 'string_list' ? ['any', 'all', 'none'] : ['in', 'not_in']
}

export function operatorLabel(operator: AdmissionFormOperator): string {
    return operator in LIST_OPERATOR_LABELS
        ? LIST_OPERATOR_LABELS[operator as AdmissionListOperator]
        : SCALAR_OPERATOR_LABELS[operator as AdmissionScalarOperator]
}

export function emptyAdmissionFilterRow(field: AdmissionRuleFieldApi): AdmissionFilterRow {
    return { field: field.field, operator: operatorsForKind(field.kind)[0], values: [] }
}

function isStoredGroup(value: unknown): value is StoredGroup {
    return (
        typeof value === 'object' &&
        value !== null &&
        ((value as StoredGroup).operator === 'AND' || (value as StoredGroup).operator === 'OR') &&
        Array.isArray((value as StoredGroup).rules)
    )
}

function rowFromStoredRule(rule: StoredRule): AdmissionFilterRow | null {
    const values = (Array.isArray(rule.value) ? rule.value : [rule.value]).map(String)
    switch (rule.operator) {
        case 'any':
        case 'all':
        case 'none':
        case 'in':
        case 'not_in':
            return { field: rule.field, operator: rule.operator, values }
        case 'eq':
            return { field: rule.field, operator: 'in', values }
        case 'neq':
            return { field: rule.field, operator: 'not_in', values }
        default:
            return null
    }
}

/**
 * The form for the stored tree, or null when the form cannot show it. The form edits one flat group.
 * The API also accepts nested groups, and the modal must not drop those without saying so.
 */
export function admissionFormFromConfig(
    config: Record<string, any> | null | undefined
): AdmissionFiltersFormValues | null {
    const stored = config?.[SOURCE_ADMISSION_RULES_KEY]
    if (stored === null || stored === undefined) {
        return { match: 'AND', rows: [] }
    }
    if (!isStoredGroup(stored)) {
        return null
    }
    const rows: AdmissionFilterRow[] = []
    for (const rule of stored.rules) {
        const row = isStoredGroup(rule) ? null : rowFromStoredRule(rule)
        if (row === null) {
            return null
        }
        rows.push(row)
    }
    return { match: stored.operator, rows }
}

/** The tree to store, or null to clear the filters. */
export function admissionRulesFromForm(
    form: AdmissionFiltersFormValues,
    fields: AdmissionRuleFieldApi[]
): StoredGroup | null {
    if (form.rows.length === 0) {
        return null
    }
    const kinds = new Map(fields.map((field) => [field.field, field.kind]))
    return {
        operator: form.match,
        rules: form.rows.map((row) => ({
            field: row.field,
            operator: row.operator,
            value: kinds.get(row.field) === 'number' ? row.values.map(Number) : row.values,
        })),
    }
}

/** The stored filter count for the roster button, or null when the stored tree is not a flat group. */
export function admissionFilterCount(config: Record<string, any> | null | undefined): number | null {
    const form = admissionFormFromConfig(config)
    return form === null ? null : form.rows.length
}

export function admissionRowError(row: AdmissionFilterRow): string | undefined {
    if (row.values.length === 0) {
        return 'Add at least one value, or remove this filter.'
    }
    return undefined
}
