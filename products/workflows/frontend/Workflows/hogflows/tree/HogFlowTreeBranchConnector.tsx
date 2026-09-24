export function HogFlowTreeBranchConnector({ isLast }: { isLast: boolean }): JSX.Element {
    return (
        <>
            <svg
                aria-hidden="true"
                className="pointer-events-none absolute start-2 -top-3 h-9 w-4 text-[var(--workflow-branch-line-color)] rtl:-scale-x-100"
                viewBox="0 0 16 36"
                fill="none"
            >
                <path
                    d={`M 1 0 V 23 A 12 12 0 0 0 13 35 H 16${!isLast ? ' M 1 23 V 36' : ''}`}
                    stroke="currentColor"
                    strokeWidth={2}
                />
            </svg>
            {!isLast && (
                <span
                    aria-hidden="true"
                    className="pointer-events-none absolute start-2 top-6 -bottom-3 border-s-2 border-[var(--workflow-branch-line-color)]"
                />
            )}
        </>
    )
}
