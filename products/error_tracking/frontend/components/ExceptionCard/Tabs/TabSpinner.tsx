import { Spinner } from '@posthog/lemon-ui'

export function TabSpinner(): JSX.Element {
    return (
        <div className="flex h-[300px] items-center justify-center">
            <Spinner />
        </div>
    )
}
