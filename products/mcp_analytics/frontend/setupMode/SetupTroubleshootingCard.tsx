import { useValues } from 'kea'

import { IconCopy, IconExternal } from '@posthog/icons'
import { LemonButton, LemonCard } from '@posthog/lemon-ui'

import { apiHostOrigin } from 'lib/utils/apiHost'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { teamLogic } from 'scenes/teamLogic'

const FLUSH_GUIDE_URL = 'https://posthog.com/docs/mcp-analytics/installation#graceful-shutdown'

const COPY = {
    title: 'Nothing showing up?',
    restart: 'Restart your server after setup. Events start with the next run.',
    credentials: "Check that your server uses this project's token and host:",
    token: 'Project token',
    host: 'Host',
    flush: 'On serverless or short-lived servers, flush events before the process ends.',
    flushLink: 'How to flush events',
}

function CopyableValue({ label, value }: { label: string; value: string }): JSX.Element {
    return (
        <div className="flex min-w-0 items-center gap-2 text-xs">
            <span className="w-24 shrink-0 text-secondary">{label}</span>
            <code className="min-w-0 flex-1 truncate" title={value}>
                {value}
            </code>
            <LemonButton
                size="xsmall"
                icon={<IconCopy />}
                tooltip={`Copy ${label.toLowerCase()}`}
                onClick={() => void copyToClipboard(value, label.toLowerCase())}
            />
        </div>
    )
}

/** What to check when the server stays silent, with this project's own token and host to compare against. */
export function SetupTroubleshootingCard(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    return (
        <LemonCard hoverEffect={false} className="flex flex-col gap-3 p-4 text-sm">
            <span className="text-base font-semibold">{COPY.title}</span>
            <ol className="m-0 flex list-decimal flex-col gap-3 pl-5">
                <li>{COPY.restart}</li>
                <li>
                    <div className="flex flex-col gap-1.5">
                        <span>{COPY.credentials}</span>
                        {currentTeam?.api_token ? (
                            <CopyableValue label={COPY.token} value={currentTeam.api_token} />
                        ) : null}
                        <CopyableValue label={COPY.host} value={apiHostOrigin()} />
                    </div>
                </li>
                <li>
                    <div className="flex flex-col items-start gap-1.5">
                        <span>{COPY.flush}</span>
                        <LemonButton
                            size="small"
                            type="secondary"
                            to={FLUSH_GUIDE_URL}
                            targetBlank
                            sideIcon={<IconExternal />}
                            data-attr="mcp-analytics-setup-mode-flush-guide"
                        >
                            {COPY.flushLink}
                        </LemonButton>
                    </div>
                </li>
            </ol>
        </LemonCard>
    )
}
