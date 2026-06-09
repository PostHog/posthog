import { IconCloud, IconGitBranch, IconPullRequest, IconRefresh } from '@posthog/icons'
import { LemonTag } from '@posthog/lemon-ui'
import { JSX, ReactNode } from 'react'

/**
 * Ported from
 * apps/code/src/renderer/features/sessions/components/GitActionMessage.tsx.
 *
 * `parseGitActionMessage` keeps its exact signature. The component is rebuilt
 * with PostHog-native UI (@posthog/icons + LemonTag + Tailwind) in place of
 * phosphor icons and Radix Box/Flex/Badge/Text.
 */

export type GitActionType = 'commit-push' | 'publish' | 'push' | 'pull' | 'sync' | 'create-pr'

const GIT_ACTION_MARKER_PREFIX = '<!-- GIT_ACTION:'
const GIT_ACTION_MARKER_SUFFIX = ' -->'

export function parseGitActionMessage(content: string): {
    isGitAction: boolean
    actionType: GitActionType | null
    prompt: string
} {
    if (!content.startsWith(GIT_ACTION_MARKER_PREFIX)) {
        return { isGitAction: false, actionType: null, prompt: content }
    }

    const markerEnd = content.indexOf(GIT_ACTION_MARKER_SUFFIX)
    if (markerEnd === -1) {
        return { isGitAction: false, actionType: null, prompt: content }
    }

    const actionType = content.slice(GIT_ACTION_MARKER_PREFIX.length, markerEnd) as GitActionType

    const prompt = content.slice(markerEnd + GIT_ACTION_MARKER_SUFFIX.length + 1) // +1 for newline

    return { isGitAction: true, actionType, prompt }
}

function getActionIcon(actionType: GitActionType): ReactNode {
    switch (actionType) {
        case 'commit-push':
            return <IconCloud />
        case 'publish':
            return <IconGitBranch />
        case 'push':
            return <IconCloud />
        case 'pull':
            return <IconRefresh />
        case 'sync':
            return <IconRefresh />
        case 'create-pr':
            return <IconPullRequest />
        default:
            return <IconCloud />
    }
}

function getActionLabel(actionType: GitActionType): string {
    switch (actionType) {
        case 'commit-push':
            return 'Commit & push'
        case 'publish':
            return 'Publish branch'
        case 'push':
            return 'Push'
        case 'pull':
            return 'Pull'
        case 'sync':
            return 'Sync'
        case 'create-pr':
            return 'Create PR'
        default:
            return 'Git action'
    }
}

interface GitActionMessageProps {
    actionType: GitActionType
}

export function GitActionMessage({ actionType }: GitActionMessageProps): JSX.Element {
    return (
        <div className="mt-4 max-w-[95%] xl:max-w-[60%]">
            <div className="flex items-center gap-2 rounded-lg border border-accent bg-accent-highlight px-3 py-2">
                <div className="flex items-center justify-center rounded bg-accent p-1 text-white">
                    {getActionIcon(actionType)}
                </div>
                <span className="font-medium text-sm">{getActionLabel(actionType)}</span>
                <LemonTag type="muted">Git action</LemonTag>
            </div>
        </div>
    )
}
