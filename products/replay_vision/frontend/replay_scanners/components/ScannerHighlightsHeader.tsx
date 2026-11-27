import { useValues } from 'kea'

import { IconList, IconPencil } from '@posthog/icons'
import { LemonButton, Tooltip } from '@posthog/lemon-ui'

import { pluralize } from 'lib/utils/strings'

import { getReplayVisionEditDisabledReason } from '../../utils/accessControl'
import { highlightFeedLogic } from '../highlightFeedLogic'
import { scannerEditUrl } from '../scannerEditorSceneLogic'
import { scannerStatusDetail } from '../scannerStatusDetail'
import type { ReplayScanner } from '../types'
import { scannerFeedIsIdle, scannerObservationsUrl, visionHomeLogic } from '../visionHomeLogic'
import { HighlightFeedRangeMenu } from './HighlightFeedRangeMenu'
import { ScannerStatusLabel } from './ScannerStatusLabel'

export function ScannerHighlightsHeader({ scanner }: { scanner: ReplayScanner }): JSX.Element {
    const { scannerStatuses } = useValues(visionHomeLogic)
    const { feedCounts } = useValues(highlightFeedLogic)
    const status = scannerStatuses[scanner.id]
    const showDetails = !scannerFeedIsIdle(status?.kind)
    return (
        <div className="flex flex-wrap items-center gap-x-1.5 gap-y-2 text-sm">
            <LemonButton
                type="tertiary"
                size="small"
                icon={<IconList />}
                to={scannerObservationsUrl(scanner.id)}
                data-attr="vision-home-scanner-all-results"
            >
                All results
            </LemonButton>
            <LemonButton
                type="tertiary"
                size="small"
                icon={<IconPencil />}
                to={scannerEditUrl(scanner.id, null)}
                disabledReason={getReplayVisionEditDisabledReason(scanner.user_access_level)}
                data-attr="vision-home-scanner-edit"
            >
                Edit scanner
            </LemonButton>
            <div className="mx-2 h-5 border-l" />
            {status && (
                <Tooltip title={scannerStatusDetail(status, null)}>
                    <span className="cursor-default" data-attr="vision-home-scanner-status">
                        <ScannerStatusLabel status={status} />
                    </span>
                </Tooltip>
            )}
            {showDetails && feedCounts && (
                <span className="text-secondary">
                    · {feedCounts.highlights === 0 ? 'No highlights' : pluralize(feedCounts.highlights, 'highlight')}{' '}
                    from {pluralize(feedCounts.observations, 'session')} scanned
                </span>
            )}
            {showDetails && (
                <div className="ml-auto">
                    <HighlightFeedRangeMenu />
                </div>
            )}
        </div>
    )
}
