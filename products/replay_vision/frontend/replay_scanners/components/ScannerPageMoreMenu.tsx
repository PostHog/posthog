import { useValues } from 'kea'
import { router } from 'kea-router'
import { useState } from 'react'

import { LemonButton, LemonDivider } from '@posthog/lemon-ui'

import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { visionScannersDestroy, visionScannersDuplicateCreate } from '../../generated/api'
import { refreshVisionQuota } from '../../logics/visionQuotaLogic'
import { visionScannersListLogic } from '../../logics/visionScannersListLogic'
import { getReplayVisionDeleteDisabledReason, getReplayVisionEditDisabledReason } from '../../utils/accessControl'
import type { ScannerFormValues } from '../types'

export function ScannerPageMoreMenu({
    scanner,
}: {
    scanner: Pick<ScannerFormValues, 'id' | 'name' | 'scanner_type' | 'user_access_level'>
}): JSX.Element | null {
    const { currentTeamId } = useValues(teamLogic)
    const [busy, setBusy] = useState<'duplicating' | 'deleting' | null>(null)
    const scannerId = scanner.id
    if (!scannerId || !currentTeamId) {
        return null
    }

    const duplicate = async (): Promise<void> => {
        setBusy('duplicating')
        try {
            // The server copies the stored config, picks a free copy name, and leaves the copy off for review.
            const response = await visionScannersDuplicateCreate(String(currentTeamId), scannerId)
            lemonToast.success('Scanner duplicated')
            router.actions.push(urls.replayVisionScannerConfigure(response.id))
        } catch (error: any) {
            lemonToast.error(`Failed to duplicate scanner${error?.detail ? `: ${error.detail}` : ''}`)
        } finally {
            setBusy(null)
        }
    }

    const remove = async (): Promise<void> => {
        setBusy('deleting')
        try {
            await visionScannersDestroy(String(currentTeamId), scannerId)
            lemonToast.success('Scanner deleted')
            visionScannersListLogic.findMounted()?.actions.loadScanners()
            refreshVisionQuota()
            router.actions.push(urls.replayVision())
        } catch (error: any) {
            lemonToast.error(`Failed to delete scanner${error?.detail ? `: ${error.detail}` : ''}`)
            setBusy(null)
        }
    }

    return (
        <More
            data-attr="vision-scanner-page-more"
            overlay={
                <>
                    <LemonButton
                        fullWidth
                        loading={busy === 'duplicating'}
                        onClick={() => void duplicate()}
                        // Duplicating creates a new scanner, so it checks resource-level edit access, not this scanner's.
                        disabledReason={getReplayVisionEditDisabledReason()}
                        data-attr="vision-scanner-duplicate"
                        data-ph-capture-attribute-scanner-type={scanner.scanner_type}
                    >
                        Duplicate
                    </LemonButton>
                    <LemonDivider />
                    <LemonButton
                        fullWidth
                        status="danger"
                        loading={busy === 'deleting'}
                        disabledReason={
                            busy === 'deleting'
                                ? 'Deleting…'
                                : getReplayVisionDeleteDisabledReason(scanner.user_access_level)
                        }
                        onClick={() =>
                            LemonDialog.open({
                                title: `Delete "${scanner.name || 'Untitled scanner'}"?`,
                                description: 'This cannot be undone.',
                                primaryButton: {
                                    children: 'Delete',
                                    status: 'danger',
                                    onClick: () => void remove(),
                                },
                                secondaryButton: { children: 'Cancel' },
                            })
                        }
                        data-attr="vision-scanner-delete"
                        data-ph-capture-attribute-scanner-type={scanner.scanner_type}
                    >
                        Delete
                    </LemonButton>
                </>
            }
        />
    )
}
