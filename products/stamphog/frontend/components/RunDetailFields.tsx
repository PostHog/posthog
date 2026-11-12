import { TZLabel } from 'lib/components/TZLabel'

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

export function TimeField({ label, time }: { label: string; time?: string | null }): JSX.Element {
    return <Field label={label}>{time ? <TZLabel time={time} /> : null}</Field>
}

export function Section({
    title,
    note,
    children,
}: {
    title: string
    note?: React.ReactNode
    children: React.ReactNode
}): JSX.Element {
    return (
        <section className="min-w-0">
            <h5 className="text-muted mb-1.5">{title}</h5>
            {/* An auto label column sits against its longest label — a fixed width would open a ragged
                gap beside the short ones. Baseline alignment keeps plain values level with the tag rows. */}
            <dl className="grid grid-cols-[auto_1fr] items-baseline gap-x-4 gap-y-1.5 text-xs">{children}</dl>
            {note && <p className="text-muted text-xs mt-2 mb-0">{note}</p>}
        </section>
    )
}
