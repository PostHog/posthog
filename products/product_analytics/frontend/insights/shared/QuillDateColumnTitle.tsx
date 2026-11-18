import { FormatDateDisplayInput, formatDateDisplay } from 'lib/components/DateDisplay/formatDateDisplay'

export function QuillDateColumnTitle(props: FormatDateDisplayInput): JSX.Element {
    const { highlight, primary, secondary } = formatDateDisplay(props)

    return (
        <span className="inline-flex items-baseline gap-1" translate="no">
            {highlight && <span className="text-subtle-foreground">{highlight}</span>}
            <span>{primary}</span>
            {secondary !== null && <span>({secondary})</span>}
        </span>
    )
}
