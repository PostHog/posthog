/** Section heading styled like a LemonTabs label (same 14px scale, tertiary color) so the
 * rail reads as a sibling of the tab bar rather than a louder header. */
export function SetupSection({ title, children }: { title: string; children: React.ReactNode }): JSX.Element {
    return (
        <div className="flex flex-col">
            <h4 className="text-sm font-medium text-tertiary mt-0 mb-3.5">{title}</h4>
            <div className="flex flex-col gap-1.5">{children}</div>
        </div>
    )
}
