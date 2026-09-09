import './HogFlowBranchNameInput.scss'

import { LemonInput } from 'lib/lemon-ui/LemonInput'

export function HogFlowBranchNameInput({
    value,
    onChange,
    placeholder,
    ariaLabel,
}: {
    value: string | undefined
    onChange: (value: string) => void
    placeholder: string
    ariaLabel: string
}): JSX.Element {
    return (
        <div className="HogFlowBranchNameInput min-w-0 flex-1">
            <LemonInput
                value={value || ''}
                onChange={onChange}
                placeholder={placeholder}
                size="small"
                transparentBackground
                className="min-w-0"
                aria-label={ariaLabel}
                data-attr="workflow-panel-select-branch"
            />
        </div>
    )
}
