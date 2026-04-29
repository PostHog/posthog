import { CostContext, formatLLMCost } from '../utils'

export function CostBreakdownTooltip({
    costContext,
    children,
}: {
    costContext: CostContext
    children?: React.ReactNode
}): JSX.Element {
    const { inputCost, outputCost, requestCost, webSearchCost, audioCost, imageCost, totalCost } = costContext
    return (
        <div className="flex flex-col gap-0.5">
            {typeof inputCost === 'number' && <div>Input: {formatLLMCost(inputCost)}</div>}
            {typeof outputCost === 'number' && <div>Output: {formatLLMCost(outputCost)}</div>}
            {/* Request, web search and modality costs are uncommon — hide zero values to reduce noise.
                Modality costs are a breakdown of input + output, NOT additive — they are shown
                indented to make that relationship visible. */}
            {typeof requestCost === 'number' && requestCost > 0 && <div>Request: {formatLLMCost(requestCost)}</div>}
            {typeof webSearchCost === 'number' && webSearchCost > 0 && (
                <div>Web search: {formatLLMCost(webSearchCost)}</div>
            )}
            {typeof audioCost === 'number' && audioCost > 0 && (
                <div className="pl-2 text-muted">Audio (incl. above): {formatLLMCost(audioCost)}</div>
            )}
            {typeof imageCost === 'number' && imageCost > 0 && (
                <div className="pl-2 text-muted">Image (incl. above): {formatLLMCost(imageCost)}</div>
            )}
            <div className="font-semibold">Total: {formatLLMCost(totalCost)}</div>
            {children}
        </div>
    )
}
