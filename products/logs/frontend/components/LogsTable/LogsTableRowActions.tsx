import { IconCopy } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { IconLink } from 'lib/lemon-ui/icons'
import { copyToClipboard } from 'lib/utils/copyToClipboard'

import { LogMessage } from '~/queries/schema/schema-general'

interface LogsTableRowActionsProps {
    log: LogMessage
}

export function LogsTableRowActions({ log }: LogsTableRowActionsProps): JSX.Element {
    const handleCopyLink = (): void => {
        const url = new URL(window.location.href)
        url.searchParams.set('highlightedLogId', log.uuid)
        void copyToClipboard(url.toString(), 'link to log')
    }

    return (
        <More
            overlay={
                <>
                    <LemonButton
                        onClick={() => {
                            void copyToClipboard(log.body, 'log message')
                        }}
                        fullWidth
                        sideIcon={<IconCopy />}
                        data-attr="logs-table-copy-message"
                    >
                        Copy log message
                    </LemonButton>
                    <LemonButton
                        onClick={handleCopyLink}
                        fullWidth
                        sideIcon={<IconLink />}
                        data-attr="logs-table-copy-link"
                    >
                        Copy link to log
                    </LemonButton>
                </>
            }
        />
    )
}
