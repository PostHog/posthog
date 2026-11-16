import { cn } from 'lib/utils/css-classes'

export function SurveyPreviewPagePlaceholder({
    isMobile,
    highlightClassName,
}: {
    isMobile: boolean
    highlightClassName: string
}): JSX.Element {
    return (
        <div className="flex w-full" aria-hidden>
            {!isMobile && (
                <div className="flex w-36 shrink-0 flex-col gap-2 border-r p-3">
                    {[0, 1, 2, 3, 4, 5].map((bar) => (
                        <span key={bar} className="h-2.5 rounded-sm bg-border" />
                    ))}
                </div>
            )}
            <div
                className={cn(
                    'm-6 flex flex-1 flex-col items-center gap-3 self-center rounded p-4',
                    highlightClassName
                )}
            >
                <span className="h-4 w-1/2 rounded-sm bg-border" />
                <span className="h-10 w-full max-w-md rounded border bg-surface-secondary" />
                <div className="flex flex-wrap justify-center gap-2">
                    {[0, 1, 2].map((chip) => (
                        <span key={chip} className="h-5 w-20 rounded-full border" />
                    ))}
                </div>
            </div>
        </div>
    )
}
