import { plainVariables } from '../stepValues'
import { tint } from '../tileCanvasModel'

const VARIABLE_SPLIT = /(\{\{?[^}]+\}?\})/g
const IS_VARIABLE = /^\{\{?[^}]+\}?\}$/

export function TextWithVariables({ text, color }: { text: string; color: string }): JSX.Element {
    return (
        <>
            {text.split(VARIABLE_SPLIT).map((part, index) =>
                IS_VARIABLE.test(part) ? (
                    <span
                        key={index}
                        className="rounded px-1 py-px font-mono text-[11px]"
                        style={{ color, backgroundColor: tint(color, 10) }}
                    >
                        {plainVariables(part)}
                    </span>
                ) : (
                    <span key={index}>{part}</span>
                )
            )}
        </>
    )
}
