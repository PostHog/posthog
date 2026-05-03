export function CheckDots({ checks }: { checks: boolean[] }): JSX.Element {
    return (
        <span className="inline-flex items-center gap-1.5">
            {checks.map((matched, i) => (
                <span
                    key={i}
                    className={`inline-block w-3 h-3 rounded-full border ${
                        matched ? 'bg-danger-highlight border-danger' : 'bg-success-highlight border-success'
                    }`}
                    title={`Check ${i + 1} (newest first): ${matched ? 'matched' : 'ok'}`}
                />
            ))}
        </span>
    )
}
