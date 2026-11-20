/** Prose values wrap at words, so pass mono={false}. Ids, hashes and paths stay monospace and break anywhere. */
export function Field({
    label,
    mono = true,
    children,
}: {
    label: string
    mono?: boolean
    children: React.ReactNode
}): JSX.Element {
    return (
        <>
            <dt className="text-muted">{label}</dt>
            <dd className={mono ? 'm-0 min-w-0 font-mono text-xs break-all' : 'm-0 min-w-0 text-xs break-words'}>
                {children ?? <span className="text-muted">—</span>}
            </dd>
        </>
    )
}
