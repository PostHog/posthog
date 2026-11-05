/** A list of short lines, each with a time on the right. Used for agent runs and activity. */
export function MockTimeList({ items }: { items: { key: string; text: string; trailing: string }[] }): JSX.Element {
    return (
        <ul className="InboxMockup__plainList">
            {items.map((item) => (
                <li key={item.key} className="flex items-baseline justify-between gap-3">
                    <span className="min-w-0">{item.text}</span>
                    <span className="InboxMockup__muted shrink-0 tabular-nums">{item.trailing}</span>
                </li>
            ))}
        </ul>
    )
}
