/** A table cell with one fact per line. The first line is the main fact, falsy lines are left out. */
export function SetupStackedCell({ lines }: { lines: (string | null | undefined | false)[] }): JSX.Element {
    const shown = lines.filter((line): line is string => !!line)
    return (
        <div className="flex flex-col text-xs" translate="no">
            {shown.map((line, index) => (
                <span key={index} className={index === 0 ? undefined : 'text-secondary'}>
                    {line}
                </span>
            ))}
        </div>
    )
}
