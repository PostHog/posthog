import { tint } from '../tileCanvasModel'
import { TextWithVariables } from './TextWithVariables'

export function AiPreview({
    prompt,
    tools,
    writes,
    color,
}: {
    prompt?: string
    tools: string[]
    writes: string[]
    color: string
}): JSX.Element | null {
    if (!prompt && !tools.length && !writes.length) {
        return null
    }
    return (
        <div className="flex flex-col gap-2 text-left text-[12.5px] leading-snug">
            {prompt && (
                <div
                    className="rounded-md border p-2.5"
                    style={{ borderColor: tint(color, 30), backgroundColor: tint(color, 6) }}
                >
                    <div className="mb-1 text-[10px] font-semibold uppercase tracking-wider" style={{ color }}>
                        Instructions
                    </div>
                    <TextWithVariables text={prompt} color={color} />
                </div>
            )}
            {tools.length > 0 && (
                <div className="flex flex-wrap items-center gap-1">
                    <span className="text-[11px] text-secondary">Can use</span>
                    {tools.map((tool) => (
                        <span key={tool} className="rounded-full border px-1.5 text-[11px]">
                            {tool}
                        </span>
                    ))}
                </div>
            )}
            {writes.length > 0 && (
                <div className="flex flex-wrap items-center gap-1">
                    <span className="text-[11px] text-secondary">Writes</span>
                    {writes.map((output) => (
                        <span
                            key={output}
                            className="rounded px-1 py-px font-mono text-[11px]"
                            style={{ color, backgroundColor: tint(color, 10) }}
                        >
                            {output}
                        </span>
                    ))}
                </div>
            )}
        </div>
    )
}
