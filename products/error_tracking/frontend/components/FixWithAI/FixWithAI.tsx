import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'

import { IconMagicWand, IconPullRequest } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import 'lib/integrations/GitHubIntegrationHelpers'

import { RepositorySelectorButton } from './RepositorySelectorButton'
import { fixWithAiLogic } from './fixWithAiLogic'

export type FixWithAIStatus = 'idle' | 'in_progress' | 'done'

export function FixWithAI(): JSX.Element {
    const { integrationId, repository, fixStatus, pullRequest } = useValues(fixWithAiLogic)
    const { generateFix } = useActions(fixWithAiLogic)

    const client = posthog.init('phc_VXlGk6yOu3agIn0h7lTmSOECAGWCtJonUJDAN4CexlJ')

    const isInProgress = fixStatus === 'in_progress'
    const isDone = fixStatus === 'done'

    if (!pullRequest) {
        return (
            <div className="flex gap-2 items-stretch">
                <RepositorySelectorButton />
                <LemonButton
                    type="primary"
                    icon={<IconMagicWand />}
                    onClick={generateFix}
                    loading={isInProgress}
                    disabled={isDone || !repository || !integrationId}
                    disabledReason={
                        !integrationId
                            ? 'No GitHub integration configured'
                            : !repository
                              ? 'Select a repository first'
                              : undefined
                    }
                    className="flex-shrink-0"
                >
                    {isInProgress ? 'Generating fix...' : isDone ? 'Fix generated' : 'Fix with AI'}
                </LemonButton>
            </div>
        )
    }

    if (pullRequest) {
        return (
            <LemonButton
                type="tertiary"
                to={pullRequest.url}
                targetBlank
                icon={<IconPullRequest />}
                onClick={() => client.capture('error_tracking_fix_with_ai_open_pr_button_clicked')}
            >
                {pullRequest.title}
            </LemonButton>
        )
    }

    return <></>
}
