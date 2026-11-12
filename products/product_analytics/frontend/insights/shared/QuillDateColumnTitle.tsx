import { DateDisplayInput, dateDisplayParts } from 'lib/components/DateDisplay/dateDisplayParts'

export function QuillDateColumnTitle(props: DateDisplayInput): JSX.Element {
    const { highlight, date, secondaryDate } = dateDisplayParts(props)

    return (
        <span className="inline-flex items-baseline gap-1" translate="no">
            {highlight && <span className="text-subtle-foreground">{highlight}</span>}
            <span>{date}</span>
            {secondaryDate && <span>({secondaryDate})</span>}
        </span>
    )
}
