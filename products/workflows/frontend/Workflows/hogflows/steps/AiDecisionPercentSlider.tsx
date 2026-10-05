import { LemonSlider } from 'lib/lemon-ui/LemonSlider'
import { LemonTag } from 'lib/lemon-ui/LemonTag'

export function AiDecisionPercentSlider({
    value,
    min,
    max,
    onChange,
}: {
    value: number
    min: number
    max: number
    onChange: (value: number) => void
}): JSX.Element {
    return (
        <div className="flex items-center gap-3">
            <LemonSlider className="flex-1" min={min} max={max} step={1} value={value} onChange={onChange} />
            <LemonTag type="highlight" className="tabular-nums">
                {`${value}%`}
            </LemonTag>
        </div>
    )
}
