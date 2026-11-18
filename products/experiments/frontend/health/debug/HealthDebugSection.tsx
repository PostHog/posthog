export interface HealthDebugSectionProps {
    title: string
    description?: string
    children: React.ReactNode
}

export function HealthDebugSection({ title, description, children }: HealthDebugSectionProps): JSX.Element {
    return (
        <section className="flex flex-col gap-2">
            <h4 className="mb-0">{title}</h4>
            {description && <p className="text-secondary text-sm mb-0">{description}</p>}
            {children}
        </section>
    )
}
