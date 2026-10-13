import { LemonTag, LemonTagType } from '@posthog/lemon-ui'

import type {
    DashboardTemplateStatusEnumApi,
    MetricsDashboardTemplateApi,
} from 'products/metrics/frontend/generated/api.schemas'

const STATUS_TAGS: Record<DashboardTemplateStatusEnumApi, { label: string; type: LemonTagType }> = {
    generating: { label: 'Generating', type: 'muted' },
    pending_review: { label: 'Pending review', type: 'warning' },
    approved: { label: 'Approved', type: 'success' },
    rejected: { label: 'Rejected', type: 'danger' },
    failed: { label: 'Failed', type: 'danger' },
}

export function DashboardTemplateStatusTag({ template }: { template: MetricsDashboardTemplateApi }): JSX.Element {
    const { label, type } = STATUS_TAGS[template.status]
    return <LemonTag type={type}>{label}</LemonTag>
}
