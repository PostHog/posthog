import { LemonCheckbox, LemonInput, LemonTag } from '@posthog/lemon-ui'

import { PlaygroundVariableSpec } from '../endpointSceneLogic'

interface EndpointPlaygroundVariableRowProps {
    spec: PlaygroundVariableSpec
    value: unknown
    sent: boolean
    errored?: boolean
    errorMessage?: string | null
    onValueChange: (value: unknown) => void
    onSentChange: (sent: boolean) => void
}

function formatValueForInput(value: unknown): string {
    if (value === null || value === undefined) {
        return ''
    }
    return String(value)
}

// Grid template shared by every variable row so the checkbox, name, tag and input columns
// line up vertically regardless of how long each variable name is. Long names truncate
// rather than push the input around (real tooltip on the `<code>` shows the full name).
const VARIABLE_ROW_GRID = 'grid grid-cols-[auto_7rem_5rem_1fr] items-center gap-2'

export function EndpointPlaygroundVariableRow({
    spec,
    value,
    sent,
    errored,
    errorMessage,
    onValueChange,
    onSentChange,
}: EndpointPlaygroundVariableRowProps): JSX.Element {
    const placeholder =
        spec.kind === 'date' ? "e.g. '-7d', '2024-01-01', 'now'" : spec.kind === 'breakdown' ? `e.g. "Chrome"` : ''

    const offButRequired = !sent && spec.required
    const showInlineError = errored && errorMessage
    const inputDisabledReason = !sent ? `Tick "Send" to include ${spec.name} in the request.` : undefined

    return (
        <div
            className={`flex flex-col gap-1 p-2 bg-accent-3000 border ${
                errored || offButRequired ? 'border-danger' : 'border-border'
            } rounded`}
        >
            <div className={`${VARIABLE_ROW_GRID} ${sent ? '' : 'opacity-60'}`}>
                <LemonCheckbox
                    checked={sent}
                    onChange={onSentChange}
                    disabledReason={
                        spec.sendLocked
                            ? `${spec.name} is required. Mark it optional in Configuration to allow omitting it.`
                            : undefined
                    }
                />
                <code className="text-sm truncate" title={spec.name}>
                    {spec.name}
                </code>
                <LemonTag type={spec.required ? 'danger' : 'muted'} size="small" className="justify-self-start">
                    {spec.required ? 'Required' : 'Optional'}
                </LemonTag>
                <LemonInput
                    value={formatValueForInput(value)}
                    onChange={(next) => onValueChange(next)}
                    disabledReason={inputDisabledReason}
                    placeholder={placeholder}
                    size="small"
                    status={errored ? 'danger' : 'default'}
                    fullWidth
                />
            </div>
            {showInlineError ? (
                <span className="text-xs text-danger pl-7">{errorMessage}</span>
            ) : offButRequired ? (
                <span className="text-xs text-danger pl-7">Required — execution will 400 until you tick Send.</span>
            ) : null}
        </div>
    )
}
