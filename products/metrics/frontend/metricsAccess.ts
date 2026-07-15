import { getAccessControlDisabledReason, userHasAccess } from 'lib/utils/accessControlUtils'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

export const getMetricsViewerDisabledReason = (): string | null =>
    getAccessControlDisabledReason(AccessControlResourceType.Metrics, AccessControlLevel.Viewer)

export const canViewMetrics = (): boolean =>
    userHasAccess(AccessControlResourceType.Metrics, AccessControlLevel.Viewer)

export const getMetricsInsightEditorDisabledReason = (): string | null =>
    getMetricsViewerDisabledReason() ??
    getAccessControlDisabledReason(AccessControlResourceType.Insight, AccessControlLevel.Editor)

export const canCreateMetricsInsight = (): boolean =>
    canViewMetrics() && userHasAccess(AccessControlResourceType.Insight, AccessControlLevel.Editor)
