import './HogFlowBranchNameInput.scss'

import { LemonInput } from 'lib/lemon-ui/LemonInput'

export function HogFlowBranchNameInput({
    branchColor,
    value,
    onChange,
    placeholder,
    ariaLabel,
}: {
    branchColor: string
    value: string | undefined
    onChange: (value: string) => void
    placeholder: string
    ariaLabel: string
}): JSX.Element {
    return (
        <div className="HogFlowBranchNameInput flex min-w-0 flex-1 items-center gap-2">
            <span className="size-2 shrink-0 rounded-full" style={{ backgroundColor: branchColor }} />
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
