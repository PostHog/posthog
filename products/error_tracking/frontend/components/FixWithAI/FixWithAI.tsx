import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import { useMemo, useState } from 'react'

import { IconExternal, IconMagicWand } from '@posthog/icons'
import { LemonButton, Popover } from '@posthog/lemon-ui'

import 'lib/integrations/GitHubIntegrationHelpers'
import { Link } from 'lib/lemon-ui/Link'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'

import { RepositorySelectorButton } from './RepositorySelectorButton'
import { fixWithAiLogic } from './fixWithAiLogic'

export type FixWithAIStatus = 'idle' | 'in_progress' | 'done'

interface PullRequest {
    id: number
    title: string
    url: string
    status: 'open' | 'merged' | 'closed'
}

export function FixWithAI(): JSX.Element {
    const [showPRsPopover, setShowPRsPopover] = useState(false)
    const { integrationId, repository, fixStatus } = useValues(fixWithAiLogic)
    const { generateFix } = useActions(fixWithAiLogic)

    const client = posthog.init('phc_VXlGk6yOu3agIn0h7lTmSOECAGWCtJonUJDAN4CexlJ')

    // Mock pull requests - replace with actual data when available
    const pullRequests: PullRequest[] = useMemo(
        () => [
            {
                id: 1,
                title: 'Fix: Resolve null pointer exception in error handling',
                url: 'https://github.com/posthog/posthog/pull/42424',
                status: 'open',
            },
            {
                id: 2,
                title: 'Fix: Improve error boundary resilience',
                url: 'https://github.com/posthog/posthog/pull/42425',
                status: 'merged',
            },
        ],
        []
    )

    const isInProgress = fixStatus === 'in_progress'
    const isDone = fixStatus === 'done'

    return (
        <div>
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

            {/* Pull Requests Popover */}
            {pullRequests.length > 0 && (
                <Popover
                    visible={showPRsPopover}
                    onClickOutside={() => setShowPRsPopover(false)}
                    overlay={
                        <div className="p-3 min-w-[320px] max-w-[400px]">
                            <div className="text-xs font-semibold text-default mb-2">Related Pull Requests</div>
                            <div className="space-y-1.5">
                                {pullRequests.map((pr) => (
                                    <Link key={pr.id} to={pr.url} target="_blank" className="block">
                                        <ButtonPrimitive
                                            fullWidth
                                            variant="outline"
                                            size="xxs"
                                            className="justify-between items-center px-2 py-1.5 hover:bg-bg-3000 transition-colors"
                                        >
                                            <div className="flex items-center gap-2 flex-1 min-w-0">
                                                <div
                                                    className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${
                                                        pr.status === 'open'
                                                            ? 'bg-success'
                                                            : pr.status === 'merged'
                                                              ? 'bg-purple'
                                                              : 'bg-muted-alt'
                                                    }`}
                                                />
                                                <span className="truncate text-xs font-medium text-default">
                                                    {pr.title}
                                                </span>
                                            </div>
                                            <div className="flex items-center gap-2 flex-shrink-0 ml-2">
                                                <span
                                                    className={`text-[10px] font-semibold uppercase ${
                                                        pr.status === 'open'
                                                            ? 'text-success'
                                                            : pr.status === 'merged'
                                                              ? 'text-purple'
                                                              : 'text-muted-alt'
                                                    }`}
                                                >
                                                    {pr.status}
                                                </span>
                                                <IconExternal className="text-muted-alt w-3 h-3" />
                                            </div>
                                        </ButtonPrimitive>
                                    </Link>
                                ))}
                            </div>
                        </div>
                    }
                    placement="top"
                    showArrow
                >
                    <div onMouseEnter={() => setShowPRsPopover(true)} onMouseLeave={() => setShowPRsPopover(false)}>
                        <ButtonPrimitive
                            variant="outline"
                            size="xxs"
                            className="text-xs text-muted-alt hover:text-default transition-colors"
                            onClick={() => client.capture('error_tracking_fix_with_ai_open_pr_button_clicked')}
                        >
                            See related pull requests ({pullRequests.length})
                        </ButtonPrimitive>
                    </div>
                </Popover>
            )}
        </div>
    )
}
