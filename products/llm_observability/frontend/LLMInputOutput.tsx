import { IconArrowDown, IconArrowUp } from 'lib/lemon-ui/icons'

export function LLMInputOutput({
    inputDisplay,
    outputDisplay,
    inputHeading = 'Input',
    outputHeading = 'Output',
}: {
    inputDisplay: JSX.Element | JSX.Element[]
    outputDisplay: JSX.Element | JSX.Element[]
    inputHeading?: string
    outputHeading?: string
}): JSX.Element {
    return (
        <div className="bg-surface-primary rounded-lg border p-2">
            <h4 className="flex items-center gap-x-1.5 text-xs font-semibold mb-2">
                <IconArrowUp className="text-base" />
                {inputHeading}
            </h4>
            {inputDisplay}
            <h4 className="flex items-center gap-x-1.5 text-xs font-semibold my-2">
                <IconArrowDown className="text-base" />
                {outputHeading}
            </h4>
            {outputDisplay}
        </div>
    )
}
