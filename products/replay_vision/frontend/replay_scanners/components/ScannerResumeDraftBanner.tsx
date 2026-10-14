import { useActions, useValues } from 'kea'
import { combineUrl, router } from 'kea-router'

import { IconPencil, IconTrash } from '@posthog/icons'
import { LemonBanner, LemonButton } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { urls } from 'scenes/urls'

import { ScannerTypeBadge } from '../../components/ScannerTypeBadge'
import { replayScannerLogic } from '../replayScannerLogic'

export function ScannerResumeDraftBanner(): JSX.Element | null {
    const logic = replayScannerLogic({ id: 'new' })
    const { scannerDraftSavedAt, scanner } = useValues(logic)
    const { discardScannerDraft } = useActions(logic)

    if (scannerDraftSavedAt === null) {
        return null
    }

    const handleResume = (): void => {
        const { template: _template, ...params } = router.values.searchParams
        router.actions.push(combineUrl(urls.replayVisionScannerDetails('new'), params).url)
    }

    return (
        <LemonBanner
            type="info"
            icon={<IconPencil />}
            action={{
                children: 'Resume draft',
                onClick: handleResume,
                'data-attr': 'vision-template-resume-draft',
            }}
        >
            <div className="flex flex-wrap items-center gap-2">
                <span className="font-semibold">Resume your draft</span>
                <span className="text-secondary font-normal">
                    {scanner?.name ? `"${scanner.name}"` : 'Untitled scanner'}
                </span>
                {scanner?.scanner_type && <ScannerTypeBadge scannerType={scanner.scanner_type} />}
                <span className="text-secondary font-normal">saved {dayjs(scannerDraftSavedAt).fromNow()}.</span>
                <LemonButton
                    size="xsmall"
                    type="tertiary"
                    status="danger"
                    icon={<IconTrash />}
                    tooltip="Discard this draft"
                    className="ml-auto"
                    data-attr="vision-template-discard-draft"
                    onClick={(): void =>
                        LemonDialog.open({
                            title: 'Discard this draft?',
                            description: 'This cannot be undone.',
                            primaryButton: {
                                children: 'Discard',
                                status: 'danger',
                                onClick: (): void => discardScannerDraft(),
                            },
                            secondaryButton: { children: 'Keep my draft' },
                        })
                    }
                />
            </div>
        </LemonBanner>
    )
}
