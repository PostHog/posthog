import { TextWithVariables } from './TextWithVariables'

export function TicketMessagePreview({
    message,
    isNote,
    color,
}: {
    message?: string
    isNote: boolean
    color: string
}): JSX.Element | null {
    return message ? (
        <div className="rounded-md border p-2.5 text-left text-[12.5px] leading-snug">
            <div className="mb-1 text-[10px] font-semibold uppercase tracking-wider text-secondary">
                {isNote ? 'Private note, only agents see it' : 'Reply, the customer sees it'}
            </div>
            <TextWithVariables text={message} color={color} />
        </div>
    ) : null
}
