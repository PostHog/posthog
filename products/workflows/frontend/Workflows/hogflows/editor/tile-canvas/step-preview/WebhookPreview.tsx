export function WebhookPreview({
    method,
    url,
    body,
}: {
    method: string
    url?: string
    body: Record<string, unknown>
}): JSX.Element {
    return (
        <div className="rounded-md border bg-surface-secondary p-2.5 text-left font-mono text-[11.5px] leading-relaxed">
            <div className="break-all">
                <span className="font-semibold">{method}</span> {url ?? 'URL not set'}
            </div>
            {Object.keys(body).length > 0 && (
                <div className="whitespace-pre-wrap text-secondary">{JSON.stringify(body, null, 2)}</div>
            )}
        </div>
    )
}
