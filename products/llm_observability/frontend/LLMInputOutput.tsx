import { IconArrowDown, IconArrowUp } from 'lib/lemon-ui/icons'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'

export function LLMInputOutput({
    inputDisplay,
    outputDisplay,
    inputHeading = 'Input',
    outputHeading = 'Output',
    bordered = false,
}: {
    inputDisplay: JSX.Element | JSX.Element[]
    outputDisplay: JSX.Element | JSX.Element[]
    inputHeading?: string
    outputHeading?: string
    bordered?: boolean
}): JSX.Element {
    return (
        <>
            <LemonDivider className="my-3" />
            <div className={bordered ? 'bg-bg-light rounded-lg border p-2' : undefined}>
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
        </>
    )
}
