import { LemonTag } from '@posthog/lemon-ui'

/**
 * Marks a value the viewer set themselves. The slot keeps its width when empty, so selects in a
 * column stay aligned whether or not a row has the mark.
 */
export function YouMark({ shown }: { shown: boolean }): JSX.Element {
    return (
        <span className="flex w-9 shrink-0 justify-center">
            {shown && (
                <LemonTag type="highlight" size="small" title="Your own choice">
                    you
                </LemonTag>
            )}
        </span>
    )
}
