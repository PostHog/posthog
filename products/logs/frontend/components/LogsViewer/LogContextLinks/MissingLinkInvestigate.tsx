import { useActions, useValues } from 'kea'

import { IconChevronDown, IconCopy, IconSearch, IconSparkles } from '@posthog/icons'
import { LemonButton, LemonMenu } from '@posthog/lemon-ui'

import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { humanList } from 'lib/utils/strings'
import { maxGlobalLogic } from 'scenes/max/maxGlobalLogic'

import { ParsedLogMessage } from 'products/logs/frontend/types'

import type { LogContextLinksSurface } from './LogContextLinks'
import { missingLinkInvestigateLogic } from './missingLinkInvestigateLogic'
import { MissingLink, buildMissingLinkPrompt } from './missingLinkPrompt'
import { captureInvestigate, missingLinkEventContext } from './missingLinkTelemetry'

function missingLabel(missing: MissingLink[]): string {
    const links = humanList(missing)
    return `${links.charAt(0).toUpperCase()}${links.slice(1)} ${missing.length > 1 ? 'links' : 'link'} missing.`
}

export function MissingLinkInvestigate({
    log,
    missing,
    surface,
    onLeave,
}: {
    log: ParsedLogMessage
    missing: MissingLink[]
    surface: LogContextLinksSurface
    onLeave?: () => void
}): JSX.Element {
    const { isMaxAvailable } = useValues(maxGlobalLogic)
    const { launching, startsSidePanelTask } = useValues(missingLinkInvestigateLogic)
    const { startTask } = useActions(missingLinkInvestigateLogic)

    const eventContext = missingLinkEventContext(log, missing, surface)

    useOnMountEffect(() => captureInvestigate('shown', eventContext))

    return (
        <div className="flex flex-wrap items-center gap-1">
            <span className="flex items-center gap-1 text-xs text-secondary">
                <IconSearch />
                <span>{missingLabel(missing)}</span>
            </span>
            <LemonMenu
                items={[
                    isMaxAvailable && {
                        label: 'PostHog AI',
                        icon: <IconSparkles />,
                        onClick: () =>
                            startTask(buildMissingLinkPrompt(log, missing), onLeave ?? (() => {}), eventContext),
                        'data-attr': `logs-${surface}-missing-link-posthog-ai`,
                    },
                    {
                        label: 'Copy prompt',
                        icon: <IconCopy />,
                        onClick: () => {
                            captureInvestigate('clicked', eventContext, { option: 'clipboard' })
                            void copyToClipboard(buildMissingLinkPrompt(log, missing), 'prompt')
                        },
                        'data-attr': `logs-${surface}-missing-link-copy-prompt`,
                    },
                ]}
            >
                <LemonButton
                    size="xsmall"
                    type="secondary"
                    sideIcon={<IconChevronDown />}
                    loading={startsSidePanelTask && launching}
                    data-attr={`logs-${surface}-missing-link-find-out-why`}
                >
                    Find out why
                </LemonButton>
            </LemonMenu>
        </div>
    )
}
