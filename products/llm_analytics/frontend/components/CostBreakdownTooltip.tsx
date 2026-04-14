import { formatLLMCost } from '../utils'

export function CostBreakdownTooltip({
    inputCost,
    outputCost,
    totalCost,
    children,
}: {
    inputCost?: number
    outputCost?: number
    totalCost: number
    children?: React.ReactNode
}): JSX.Element {
    return (
        <div className="flex flex-col gap-0.5">
            {typeof inputCost === 'number' && <div>Input: {formatLLMCost(inputCost)}</div>}
            {typeof outputCost === 'number' && <div>Output: {formatLLMCost(outputCost)}</div>}
            <div className="font-semibold">Total: {formatLLMCost(totalCost)}</div>
            {children}
        </div>
    )
}
