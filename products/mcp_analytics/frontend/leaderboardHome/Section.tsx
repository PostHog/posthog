import { type ReactNode } from 'react'

export function Section({ title, children }: { title: string; children: ReactNode }): JSX.Element {
    return (
        <section className="flex min-w-0 flex-col gap-4" data-quill>
            <h2 className="mb-0 text-xl font-semibold text-primary">{title}</h2>
            {children}
        </section>
    )
}
