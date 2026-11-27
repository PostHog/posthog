import { AiVisibilityTag } from './AiVisibilityTag'

/** The result of a check from an engine that answers without search, which can mention the brand but never cite it. */
export const ContentAutopilotMentionResultTag = ({
    mentioned,
    checkFailed,
}: {
    mentioned: boolean
    checkFailed: boolean
}): JSX.Element =>
    checkFailed ? (
        <AiVisibilityTag type="danger">Failed</AiVisibilityTag>
    ) : mentioned ? (
        <AiVisibilityTag type="success">Mentioned</AiVisibilityTag>
    ) : (
        <AiVisibilityTag type="warning">Not mentioned</AiVisibilityTag>
    )
