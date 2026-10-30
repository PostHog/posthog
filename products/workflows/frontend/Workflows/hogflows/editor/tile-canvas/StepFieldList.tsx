import type { StepFacts } from './stepFacts'

export function StepFieldList({ facts }: { facts: StepFacts }): JSX.Element | null {
    if (!facts.fields.length) {
        return null
    }
    return (
        <dl className="ph-no-capture m-0 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-left text-[12.5px] leading-snug">
            {facts.fields.map(([label, value]) => (
                <div key={label} className="contents">
                    <dt className="text-secondary">{label}</dt>
                    <dd className="m-0 min-w-0 break-words">{value}</dd>
                </div>
            ))}
        </dl>
    )
}
