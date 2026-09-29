/** +added / -removed mono stat chip for a diff. */
export function DiffStats({ added, removed }: { added: number; removed: number }): JSX.Element {
    return (
        <span className="font-mono text-xs shrink-0">
            <span className="text-success">+{added}</span> <span className="text-danger">-{removed}</span>
        </span>
    )
}
