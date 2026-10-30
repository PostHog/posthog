export function SearchAndAiSectionHeading({
    children,
    description,
}: {
    children: React.ReactNode
    description?: string
}): JSX.Element {
    return (
        <div className="mb-4">
            <h2 className="mb-0 text-xl font-semibold text-primary">{children}</h2>
            {description ? <p className="m-0 text-sm text-secondary">{description}</p> : null}
        </div>
    )
}
