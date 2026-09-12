/** Section label for the setup rail. Deliberately unlike a LemonTabs label (smaller, uppercase,
 * secondary color), because the rail sits beside the real tab bar and a heading at the tab scale
 * reads as a tab that does nothing when you click it. */
export function SetupSection({ title, children }: { title: string; children: React.ReactNode }): JSX.Element {
    return (
        <div className="flex flex-col">
            <h4 className="text-xs font-semibold uppercase tracking-wide text-secondary mt-0 mb-2.5">{title}</h4>
            <div className="flex flex-col gap-1.5">{children}</div>
        </div>
    )
}
