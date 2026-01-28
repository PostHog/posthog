import { useActions } from 'kea'

import { IconCopy } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { IconLink } from 'lib/lemon-ui/icons'
import { copyToClipboard } from 'lib/utils/copyToClipboard'

import { ParsedLogMessage } from 'products/logs/frontend/types'

import { logsViewerLogic } from './logsViewerLogic'

interface LogsViewerRowActionsProps {
    log: ParsedLogMessage
}

export function LogsViewerRowActions({ log }: LogsViewerRowActionsProps): JSX.Element {
    const { copyLinkToLog } = useActions(logsViewerLogic)

    return (
        <More
            overlay={
                <>
                    <LemonButton
                        onClick={() => copyToClipboard(log.body, 'log message')}
                        fullWidth
                        sideIcon={<IconCopy />}
                        data-attr="logs-viewer-copy-message"
                    >
                        Copy log message
                    </LemonButton>
                    <LemonButton
                        onClick={() => copyLinkToLog(log.uuid)}
                        fullWidth
                        sideIcon={<IconLink />}
                        data-attr="logs-viewer-copy-link"
                    >
                        Copy link to log
                    </LemonButton>
                </>
            }
        />
    )
}
