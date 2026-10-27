import { useActions, useValues } from 'kea'

import { IconGithub } from '@posthog/icons'
import {
    Button,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuTrigger,
} from '@posthog/quill-primitives'

import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { cn } from 'lib/utils/css-classes'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'

import { COMPOSER_MENU_CLASS } from '../../../components/quill/composerMenuClass'
import { githubAuthorizeUrl } from './githubAuthorizeUrl'

export interface QuillGitHubAccountMenuProps {
    integrationId: number
    onSelect: (integrationId: number) => void
    fullWidth?: boolean
}

export function QuillGitHubAccountMenu({
    integrationId,
    onSelect,
    fullWidth,
}: QuillGitHubAccountMenuProps): JSX.Element | null {
    const { getIntegrationsByKind } = useValues(integrationsLogic)
    const { reportIntegrationConnectClicked } = useActions(eventUsageLogic)
    const githubIntegrations = getIntegrationsByKind(['github'])
    if (githubIntegrations.length < 2) {
        return null
    }
    const current = githubIntegrations.find((integration) => integration.id === integrationId)?.display_name

    return (
        <DropdownMenu>
            <DropdownMenuTrigger
                render={
                    <Button
                        variant="outline"
                        size="sm"
                        aria-label={`GitHub account: ${current ?? 'GitHub'}`}
                        className={cn(fullWidth && 'h-7 w-full justify-start')}
                        data-attr="task-composer-github-account"
                    >
                        <IconGithub className="shrink-0" />
                        <span className={cn('truncate', !fullWidth && 'max-w-28')}>{current ?? 'GitHub'}</span>
                    </Button>
                }
            />
            <DropdownMenuContent
                align="start"
                side="top"
                sideOffset={6}
                className={cn('min-w-fit', COMPOSER_MENU_CLASS)}
            >
                {githubIntegrations.map((integration) => (
                    <DropdownMenuItem key={integration.id} onClick={() => onSelect(integration.id)}>
                        {integration.display_name}
                    </DropdownMenuItem>
                ))}
                <DropdownMenuItem
                    render={<LinkPrimitive to={githubAuthorizeUrl} disableClientSideRouting />}
                    onClick={() => reportIntegrationConnectClicked('github', 'github', 'task_composer')}
                >
                    Connect another
                </DropdownMenuItem>
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
