export function HealthPanelSection({ title, children }: { title: string; children: React.ReactNode }): JSX.Element {
    return (
        <section className="flex flex-col gap-1">
            <h4 className="m-0 text-xs font-semibold text-secondary">{title}</h4>
            {children}
        </section>
    )
}
