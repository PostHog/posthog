import './StyleVariables.scss'

export function StyleVariables({
    children,
    className,
}: {
    children: React.ReactNode
    className?: string
}): JSX.Element {
    return (
        <div data-quill className={`ErrorTrackingStyleVariables ${className ?? ''}`}>
            <div data-not-quill className="contents">
                {children}
            </div>
        </div>
    )
}
