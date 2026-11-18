export function StepCountLine({ count }: { count: number | undefined }): JSX.Element | null {
    if (count === undefined) {
        return null
    }
    return (
        <div className="text-xs">
            <span className="font-semibold" translate="no">
                {count.toLocaleString()}
            </span>
            <span className="text-secondary">&nbsp;{count === 1 ? 'person' : 'people'} reached this step</span>
        </div>
    )
}
