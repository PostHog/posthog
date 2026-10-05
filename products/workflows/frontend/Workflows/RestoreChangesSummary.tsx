import type { HogFlowRestoreChangesApi } from '../generated/api.schemas'

const SETTING_LABELS: Record<string, string> = {
    edges: 'step connections',
    trigger_masking: 'trigger frequency',
    conversion: 'conversion goal',
    exit_condition: 'exit condition',
    email_sending_rate_limit: 'email sending limit',
    abort_action: 'abort step',
    variables: 'variables',
}

export function restoreChangesAreEmpty(changes: HogFlowRestoreChangesApi): boolean {
    return (
        !changes.removed_steps.length &&
        !changes.added_steps.length &&
        !changes.updated_steps.length &&
        !changes.updated_settings.length
    )
}

export function RestoreChangesSummary({ changes }: { changes: HogFlowRestoreChangesApi }): JSX.Element | null {
    if (restoreChangesAreEmpty(changes)) {
        return null
    }
    const rows: [string, string[]][] = [
        ['Removes steps', changes.removed_steps],
        ['Changes steps', changes.updated_steps],
        ['Adds steps', changes.added_steps],
        ['Changes', changes.updated_settings.map((field) => SETTING_LABELS[field] ?? field)],
    ]
    return (
        <ul className="ml-5 list-disc">
            {rows
                .filter(([, names]) => names.length)
                .map(([label, names]) => (
                    <li key={label}>
                        {label}: <strong>{names.join(', ')}</strong>
                    </li>
                ))}
        </ul>
    )
}
