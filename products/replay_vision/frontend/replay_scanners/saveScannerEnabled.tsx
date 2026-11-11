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

export function confirmDialogProps(dialog: ConfirmDialog): LemonDialogProps {
    return {
        title: dialog.title,
        description: dialog.description,
        primaryButton: { children: dialog.confirmLabel, 'data-attr': dialog.confirmDataAttr },
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

/** Opens a dialog and resolves whether its primary action completed before it closed. */
function openForDecision(props: LemonDialogProps): Promise<boolean> {
    return new Promise((resolve) => {
        let confirmed = false
        const primary = props.primaryButton
        LemonDialog.open({
            ...props,
            primaryButton: primary && {
                ...primary,
                onClick: (event) => {
                    const result: unknown = primary.onClick?.(event)
                    if (!(result instanceof Promise)) {
                        confirmed = true
                        return
                    }
                    // An awaited submit that throws keeps the dialog open, so only success counts.
                    return result.then(() => {
                        confirmed = true
                    })
                },
            },
            onAfterClose: () => resolve(confirmed),
        })
    })
}

async function acceptAIConsent(): Promise<void> {
    const organization = organizationLogic.values.currentOrganization
    if (organization) {
        // Approving can trigger an SSO reauthentication redirect, so aiConsentLogic finishes it on return.
        const { pathname, search, hash } = window.location
        aiConsentLogic.actions.setPendingApprovalRedirect({
            url: `${pathname}${search}${hash}`,
            organizationId: organization.id,
            setAt: Date.now(),
        })
    }
    await aiConsentLogic.asyncActions.acceptDataProcessing()
}

async function allowAIAnalysis(): Promise<boolean> {
    const unmount = aiConsentLogic.mount()
    try {
        if (aiConsentLogic.values.dataProcessingApprovalDisabledReason) {
            LemonDialog.open(aiAnalysisOffDialogProps())
            return false
        }
        return (
            (await openForDecision(confirmDialogProps(ALLOW_AI_ANALYSIS_DIALOG))) &&
            (await openForDecision(aiConsentLegalDialogProps({ onConfirm: acceptAIConsent })))
        )
    } finally {
        unmount()
    }
}

async function enable(teamId: string, scannerId: string, takeOver: boolean): Promise<ReplayScannerApi | null> {
    try {
        return await visionScannersPartialUpdate(teamId, scannerId, {
            enabled: true,
            ...(takeOver && { take_over_as_creator: true }),
        })
    } catch (error: any) {
        if (error?.code === AI_CONSENT_REQUIRED_CODE) {
            return (await allowAIAnalysis()) ? enable(teamId, scannerId, takeOver) : null
        }
        if (error?.code === CREATOR_LOST_ACCESS_CODE && !takeOver) {
            return (await openForDecision(confirmDialogProps(TAKE_OVER_DIALOG)))
                ? enable(teamId, scannerId, true)
                : null
        }
        throw error
    }
}

async function turnOnScanner(teamId: string, scannerId: string): Promise<ReplayScannerApi | null> {
    const organization = organizationLogic.values.currentOrganization
    // Unknown consent is left to the server, which answers with the code `enable` handles.
    if (organization && !organization.is_ai_data_processing_approved && !(await allowAIAnalysis())) {
        return null
    }
    return enable(teamId, scannerId, false)
}

/**
 * Turns a scanner on or off. Turning on first asks the person to allow AI analysis or take the
 * scanner over when it can't run otherwise, and resolves null when they decline.
 */
export function saveScannerEnabled(
    teamId: string,
    scannerId: string,
    enabled: boolean
): Promise<ReplayScannerApi | null> {
    return enabled
        ? turnOnScanner(teamId, scannerId)
        : visionScannersPartialUpdate(teamId, scannerId, { enabled: false })
}
