import type { BranchPath } from '../stepPresentation'
import { pathColor } from '../tileCanvasModel'

export function BranchPreview({ paths }: { paths: BranchPath[] }): JSX.Element | null {
    if (!paths.length) {
        return null
    }
    return (
        <div className="flex flex-col gap-1 text-left text-[12.5px]">
            {paths.map((path) => (
                <div key={path.name} className="flex items-baseline gap-2 rounded-md border px-2.5 py-1">
                    <span className="size-2 shrink-0 rounded-full" style={{ backgroundColor: pathColor(path.edge) }} />
                    <span className="font-semibold">{path.name}</span>
                    <span className="min-w-0 break-words text-secondary">{path.rule}</span>
                </div>
            ))}
        </div>
    )
}
