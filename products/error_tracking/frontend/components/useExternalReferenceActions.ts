import { useAsyncActions, useValues } from 'kea'
import posthog from 'posthog-js'

import { ErrorTrackingFingerprint } from 'lib/components/Errors/types'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { addProjectIdIfMissing } from 'lib/utils/kea-router'
import { urls } from 'scenes/urls'

import { errorTrackingIssueSceneLogic } from '../scenes/ErrorTrackingIssueScene/errorTrackingIssueSceneLogic'
import { ERROR_TRACKING_INTEGRATIONS, ErrorTrackingIntegration } from './errorTrackingIntegrations'
import { openCreateIssueDialog, openLinkIssueDialog } from './externalIssueDialogs'

// pinned: analytics property value - dashboards compare the entry points against each other
export type ExternalReferenceSource = 'scene_panel' | 'issue_header'

export interface ExternalReferenceActions {
    integrations: ErrorTrackingIntegration[]
    loading: boolean
    busy: boolean
    createIssue: (integration: ErrorTrackingIntegration) => void
    linkIssue: (integration: ErrorTrackingIntegration) => void
}

export function useExternalReferenceActions(source: ExternalReferenceSource): ExternalReferenceActions {
    const { issue, issueLoading, issueFingerprints } = useValues(errorTrackingIssueSceneLogic)
    // Awaitable so the dialogs can hold their submit button in a loading state until the
    // provider request settles, rather than closing while it is still in flight.
    const { createExternalReference, linkExternalReference } = useAsyncActions(errorTrackingIssueSceneLogic)
    const { getIntegrationsByKind, integrationsLoading } = useValues(integrationsLogic)

    return {
        // An uninstalled or suspended GitHub App keeps its integration row, but it cannot reach
        // the provider, so an action on that row fails only after the user fills in the dialog.
        integrations: (getIntegrationsByKind([...ERROR_TRACKING_INTEGRATIONS]) as ErrorTrackingIntegration[]).filter(
            (integration) => integration.installation_status !== 'unavailable'
        ),
        loading: !issue || integrationsLoading,
        busy: !!issue && issueLoading,
        createIssue: (integration: ErrorTrackingIntegration): void => {
            if (!issue) {
                return
            }
            // pinned: analytics event name - renaming breaks the external reference funnel
            posthog.capture('error_tracking_external_issue_create_started', {
                issue_id: issue.id,
                integration_kind: integration.kind,
                source,
            })
            openCreateIssueDialog(issue, getIssueUrl(issueFingerprints), integration, createExternalReference)
        },
        linkIssue: (integration: ErrorTrackingIntegration): void => {
            if (!issue) {
                return
            }
            // pinned: analytics event name - renaming breaks the external reference funnel
            posthog.capture('error_tracking_external_issue_link_started', {
                issue_id: issue.id,
                integration_kind: integration.kind,
                source,
            })
            openLinkIssueDialog(integration, linkExternalReference)
        },
    }
}

// Link through the fingerprint redirect page when possible — it resolves to whatever issue the
// fingerprint belongs to at click time, so external issue links survive merges. Fingerprints are
// listed oldest-first; the oldest one is the stable, canonical one for an issue.
function getIssueUrl(fingerprints: ErrorTrackingFingerprint[]): string {
    const canonicalFingerprint = fingerprints[0]?.fingerprint
    if (canonicalFingerprint) {
        return `${window.location.origin}${addProjectIdIfMissing(urls.errorTrackingFingerprint(canonicalFingerprint))}`
    }
    return `${window.location.origin}${window.location.pathname}`
}
