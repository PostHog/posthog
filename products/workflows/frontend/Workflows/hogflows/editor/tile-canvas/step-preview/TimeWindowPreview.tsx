import type { TimeSpan } from '../stepPresentation'

const WEEK = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

export function TimeWindowPreview({ spans, color }: { spans: TimeSpan[][]; color: string }): JSX.Element {
    return (
        <div className="flex flex-col gap-1 text-left text-[11px]">
            {WEEK.map((name, index) => (
                <div key={name} className="flex items-center gap-1.5">
                    <span className="w-7 text-secondary">{name}</span>
                    <span className="relative h-2 flex-1 rounded-full bg-surface-secondary">
                        {spans[index].map(({ start, end }) => (
                            <span
                                key={start}
                                className="absolute inset-y-0 rounded-full"
                                style={{
                                    backgroundColor: color,
                                    left: `${(start / 24) * 100}%`,
                                    width: `${((end - start) / 24) * 100}%`,
                                }}
                            />
                        ))}
                    </span>
                </div>
            ))}
        </div>
    )
}
