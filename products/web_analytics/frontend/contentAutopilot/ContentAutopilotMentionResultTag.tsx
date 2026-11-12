import { LemonTag } from '@posthog/lemon-ui'

/** The result of a check from an engine that answers without search, which can mention the brand but never cite it. */
export const ContentAutopilotMentionResultTag = ({
    mentioned,
    checkFailed,
}: {
    mentioned: boolean
    checkFailed: boolean
}): JSX.Element =>
    checkFailed ? (
        <LemonTag type="danger">Failed</LemonTag>
    ) : mentioned ? (
        <LemonTag type="success">Mentioned</LemonTag>
    ) : (
        <LemonTag type="warning">Not mentioned</LemonTag>
    )
