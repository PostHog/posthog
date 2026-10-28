import { LemonTag } from '@posthog/lemon-ui'

export const ContentAutopilotCheckResultTag = ({
    cited,
    checkFailed,
}: {
    cited: boolean
    checkFailed: boolean
}): JSX.Element =>
    checkFailed ? (
        <LemonTag type="danger">Failed</LemonTag>
    ) : cited ? (
        <LemonTag type="success">Cited</LemonTag>
    ) : (
        <LemonTag type="warning">Not cited</LemonTag>
    )
