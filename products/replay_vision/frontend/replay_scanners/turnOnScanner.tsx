import { LemonDialog, LemonDialogProps } from 'lib/lemon-ui/LemonDialog'
import { organizationLogic } from 'scenes/organizationLogic'
import { AIAccessRequest } from 'scenes/settings/organization/AIAccessRequest'
import { aiConsentLegalDialogProps } from 'scenes/settings/organization/aiConsentCopy'

import { aiConsentLogic } from '~/layout/ai/aiConsentLogic'

import { visionScannersPartialUpdate } from '../generated/api'
import type { ReplayScannerApi } from '../generated/api.schemas'

// The server's error codes for a turn-on that needs the person's decision first.
const AI_CONSENT_REQUIRED_CODE = 'ai_data_processing_not_approved'
const CREATOR_LOST_ACCESS_CODE = 'scanner_creator_lost_access'

interface ConfirmDialog {
    title: string
    description: string
    confirmLabel: string
    confirmDataAttr: string
}

export const ALLOW_AI_ANALYSIS_DIALOG: ConfirmDialog = {
    title: 'Allow AI analysis to turn this scanner on?',
    description:
        "Scanners send recordings to external AI providers for analysis. Your organization hasn't allowed this yet, so the scanner can't run until it does.",
    confirmLabel: 'Allow AI analysis',
    confirmDataAttr: 'vision-scanner-turn-on-allow-ai',
}

export const TAKE_OVER_DIALOG: ConfirmDialog = {
    title: 'Take over this scanner?',
    description:
        "The person who created this scanner can no longer view recordings, so it can't run as them. Turning it on makes you its creator, and it will scan recordings as you.",
    confirmLabel: 'Take over and turn on',
    confirmDataAttr: 'vision-scanner-turn-on-take-over',
}

export function confirmDialogProps(dialog: ConfirmDialog, onConfirm: () => void): LemonDialogProps {
    return {
        title: dialog.title,
        description: dialog.description,
        primaryButton: { children: dialog.confirmLabel, 'data-attr': dialog.confirmDataAttr, onClick: onConfirm },
        secondaryButton: { children: 'Keep it off' },
    }
}

/** Shown to a member who can't allow AI analysis themselves. */
export function aiAnalysisOffDialogProps(): LemonDialogProps {
    return {
        title: 'AI analysis is off for this organization',
        description:
            'Scanners need AI analysis to run. An organization admin or owner can allow it, and then you can turn this scanner on.',
        content: <AIAccessRequest size="small" />,
        primaryButton: { children: 'Close', type: 'secondary' },
    }
}

/** Opens a dialog and resolves whether the person confirmed it. */
function confirmInDialog(dialog: ConfirmDialog): Promise<boolean> {
    return new Promise((resolve) => {
        let confirmed = false
        LemonDialog.open({
            ...confirmDialogProps(dialog, () => {
                confirmed = true
            }),
            onAfterClose: () => resolve(confirmed),
        })
    })
}

function approveAIConsent(): Promise<boolean> {
    return new Promise((resolve) => {
        let approved = false
        LemonDialog.open({
            ...aiConsentLegalDialogProps({
                onConfirm: async () => {
                    const unmount = aiConsentLogic.mount()
                    try {
                        await aiConsentLogic.asyncActions.acceptDataProcessing()
                        approved = true
                    } finally {
                        unmount()
                    }
                },
            }),
            onAfterClose: () => resolve(approved),
        })
    })
}

async function allowAIAnalysis(): Promise<boolean> {
    if (!organizationLogic.values.isAdminOrOwner) {
        LemonDialog.open(aiAnalysisOffDialogProps())
        return false
    }
    return (await confirmInDialog(ALLOW_AI_ANALYSIS_DIALOG)) && (await approveAIConsent())
}

async function enable(teamId: string, scannerId: string, takeOver: boolean): Promise<ReplayScannerApi | null> {
    try {
        return await visionScannersPartialUpdate(
            teamId,
            scannerId,
            takeOver ? { enabled: true, take_over_as_creator: true } : { enabled: true }
        )
    } catch (error: any) {
        if (error?.code === AI_CONSENT_REQUIRED_CODE) {
            return (await allowAIAnalysis()) ? enable(teamId, scannerId, takeOver) : null
        }
        if (error?.code === CREATOR_LOST_ACCESS_CODE && !takeOver) {
            return (await confirmInDialog(TAKE_OVER_DIALOG)) ? enable(teamId, scannerId, true) : null
        }
        throw error
    }
}

/**
 * Turns a scanner on, first asking the person to allow AI analysis or take the scanner over when
 * it can't run otherwise. Resolves null when they decline, and the scanner stays off.
 */
export async function turnOnScanner(teamId: string, scannerId: string): Promise<ReplayScannerApi | null> {
    if (!organizationLogic.values.currentOrganization?.is_ai_data_processing_approved && !(await allowAIAnalysis())) {
        return null
    }
    return enable(teamId, scannerId, false)
}
