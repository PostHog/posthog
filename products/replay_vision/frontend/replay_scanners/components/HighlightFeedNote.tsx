export function HighlightFeedNote({ children }: { children: React.ReactNode }): JSX.Element {
    return (
        <div className="flex flex-col items-center gap-2 text-sm text-secondary border border-dashed rounded p-6 text-center">
            {children}
        </div>
    )
}
