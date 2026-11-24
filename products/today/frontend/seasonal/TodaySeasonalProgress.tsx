import { Text } from '@posthog/quill'

export function TodaySeasonalProgress({ done, total }: { done: number; total: number }): JSX.Element {
    return (
        <div className="flex items-center gap-2">
            <div
                role="progressbar"
                aria-label="Checklist progress"
                aria-valuemin={0}
                aria-valuemax={total}
                aria-valuenow={done}
                className="TodaySeasonalProgress"
            >
                <div className="TodaySeasonalProgress__fill" style={{ width: `${(done / total) * 100}%` }} />
            </div>
            <Text size="xs" className="m-0 text-muted-foreground" translate="no">
                {`${done} of ${total} done`}
            </Text>
        </div>
    )
}
