import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'

import { IconMagicWand, IconPullRequest } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import 'lib/integrations/GitHubIntegrationHelpers'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'

import { RepositorySelectorButton } from './RepositorySelectorButton'
import { fixWithAiLogic } from './fixWithAiLogic'

export type FixWithAIStatus = 'idle' | 'in_progress' | 'done'

export function FixWithAI(): JSX.Element {
    const { integrationId, repository, fixStatus, pullRequests } = useValues(fixWithAiLogic)
    const { generateFix } = useActions(fixWithAiLogic)

    const client = posthog.init('phc_VXlGk6yOu3agIn0h7lTmSOECAGWCtJonUJDAN4CexlJ')

    const isInProgress = fixStatus === 'in_progress'

    return (
        <div className="flex flex-col gap-2">
            <div className="flex gap-2 items-stretch">
                <RepositorySelectorButton />
                <LemonButton
                    type="primary"
                    icon={<IconMagicWand />}
                    onClick={generateFix}
                    loading={isInProgress}
                    disabled={!repository || !integrationId}
                    disabledReason={
                        !integrationId
                            ? 'No GitHub integration configured'
                            : !repository
                              ? 'Select a repository first'
                              : undefined
                    }
                    className="flex-shrink-0"
                >
                    {isInProgress ? 'Generating fix...' : 'Fix with AI'}
                </LemonButton>
            </div>
            {isInProgress && (
                <div className="text-xs text-muted text-right">This may take a couple of minutes to complete</div>
            )}
            <div className="flex flex-col gap-1">
                {pullRequests.map((pullRequest) => (
                    <ButtonPrimitive
                        key={pullRequest.id}
                        fullWidth
                        onClick={() => client.capture('error_tracking_fix_with_ai_open_pr_button_clicked')}
                    >
                        <IconPullRequest />
                        {pullRequest.title}
                    </ButtonPrimitive>
                ))}
            </div>
        </div>
    )
}
