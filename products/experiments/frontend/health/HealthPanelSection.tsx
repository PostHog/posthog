export function HealthPanelSection({ title, children }: { title: string; children: React.ReactNode }): JSX.Element {
    return (
        <section className="flex flex-col gap-2">
            <h4 className="m-0 text-sm font-semibold">{title}</h4>
            {children}
        </section>
    )
}
