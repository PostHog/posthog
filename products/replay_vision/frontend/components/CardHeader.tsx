/** Card header — a muted icon plus title, shared across Replay vision config and observation cards. */
export function CardHeader({ icon, title }: { icon: JSX.Element; title: string }): JSX.Element {
    return (
        <div className="flex items-center gap-2 mb-3">
            <span className="text-muted text-base flex">{icon}</span>
            <span className="text-sm font-medium">{title}</span>
        </div>
    )
}
