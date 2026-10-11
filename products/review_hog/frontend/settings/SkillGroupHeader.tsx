/** The heading of one kind of review skill inside the review skills panel. */
export function SkillGroupHeader({ title, rule, note }: { title: string; rule: string; note?: string }): JSX.Element {
    return (
        <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5 border-t border-primary px-4 pt-3 pb-1">
            <h4 className="m-0 text-sm font-semibold">{title}</h4>
            <span className="text-xs text-secondary">{rule}</span>
            {note && <span className="text-xs text-secondary">· {note}</span>}
        </div>
    )
}
