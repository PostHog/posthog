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
        <div className="HogFlowBranchNameInput flex min-w-0 flex-1 items-center">
            <LemonInput
                value={value || ''}
                onChange={onChange}
                placeholder={placeholder}
                size="small"
                transparentBackground
                className="min-w-0 flex-1"
                aria-label={ariaLabel}
                data-attr="workflow-panel-select-branch"
            />
        </div>
    )
}
