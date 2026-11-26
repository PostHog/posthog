import { useActions, useValues } from 'kea'

import { IconGithub } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { codeEmailLogic } from './codeEmailLogic'

export function FindInGitHubButton(): JSX.Element | null {
    const { canFindInGitHub, editDisabledReason, sourceCandidatesLoading } = useValues(codeEmailLogic)
    const { findSourceCandidates } = useActions(codeEmailLogic)
    if (!canFindInGitHub) {
        return null
    }
    return (
        <LemonButton
            size="xsmall"
            type="tertiary"
            icon={<IconGithub />}
            onClick={findSourceCandidates}
            disabledReason={editDisabledReason ?? (sourceCandidatesLoading ? 'Searching GitHub' : undefined)}
            data-attr="code-email-find-source-in-github"
        >
            Find in GitHub
        </LemonButton>
    )
}
