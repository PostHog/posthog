import { useActions, useValues } from 'kea'

import { IconCopy, IconSearch, IconSparkles } from '@posthog/icons'
import { LemonButton, LemonMenu } from '@posthog/lemon-ui'

import { ParsedLogMessage } from 'products/logs/frontend/types'

import type { LogContextLinksSurface } from './LogContextLinks'
import { missingLinkInvestigateLogic } from './missingLinkInvestigateLogic'
import { MissingLink } from './missingLinkPrompt'

function missingLabel(names: MissingLink[]): string {
    return names.length <= 1 ? `No ${names[0]}` : `No ${names.slice(0, -1).join(', ')} or ${names[names.length - 1]}`
}

export interface MissingLinkInvestigateProps {
    log: ParsedLogMessage
    missing: MissingLink[]
    surface: LogContextLinksSurface
}

export function MissingLinkInvestigate({ log, missing, surface }: MissingLinkInvestigateProps): JSX.Element {
    const { taskDisabledReason } = useValues(missingLinkInvestigateLogic)
    const { copyPrompt, startTask } = useActions(missingLinkInvestigateLogic)

    return (
        <LemonMenu
            items={[
                {
                    label: 'Copy prompt for your agent',
                    icon: <IconCopy />,
                    onClick: () => copyPrompt(log, missing, surface),
                    'data-attr': `logs-${surface}-missing-link-copy-prompt`,
                },
                {
                    label: 'Investigate with PostHog AI',
                    icon: <IconSparkles />,
                    disabledReason: taskDisabledReason ?? undefined,
                    onClick: () => startTask(log, missing, surface),
                    'data-attr': `logs-${surface}-missing-link-start-task`,
                },
            ]}
        >
            <LemonButton
                size="xsmall"
                type="tertiary"
                icon={<IconSearch />}
                tooltip="Find out why this log can't link to everything it could"
                data-attr={`logs-${surface}-missing-link-investigate`}
            >
                {missingLabel(missing)} · Investigate why
            </LemonButton>
        </LemonMenu>
    )
}
