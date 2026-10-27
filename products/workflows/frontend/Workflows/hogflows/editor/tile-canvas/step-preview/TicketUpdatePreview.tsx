import { tint } from '../tileCanvasModel'

export function TicketUpdatePreview({
    status,
    tags,
    color,
}: {
    status?: string
    tags: string[]
    color: string
}): JSX.Element {
    return (
        <div className="flex flex-wrap items-center gap-1.5 rounded-md border p-2.5 text-left text-[12.5px]">
            <span className="text-secondary">Ticket</span>
            {tags.map((tag) => (
                <span key={tag} className="rounded-full px-2" style={{ color, backgroundColor: tint(color, 10) }}>
                    {tag}
                </span>
            ))}
            {status && <span>Status: {status}</span>}
        </div>
    )
}
