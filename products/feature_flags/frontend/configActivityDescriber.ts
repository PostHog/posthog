import { ActivityChange, ActivityLogItem, ChangeMapping } from 'lib/components/ActivityLog/humanizeActivity'

const fieldLabels: Record<string, string> = {
    default_value: 'default value',
    return_type: 'return type',
    aggregation_group_type_index: 'aggregation group',
    targeting: 'targeting',
    rollout_percentage: 'rollout percentage',
    on_rollout_miss: 'rollout miss behavior',
    value: 'value',
    description: 'description',
    metadata: 'metadata',
    rule_type: 'type',
    seed: 'assignment identity',
    assignment_algorithm: 'assignment algorithm',
    assign_by: 'assignment property',
}

function isLegacyConfig(value: unknown): boolean {
    if (value == null) {
        return true
    }
    return typeof value === 'object' && !Array.isArray(value) && (!('version' in value) || value.version === 1)
}

export function describeConfigActivity(change: ActivityChange, logItem?: ActivityLogItem): ChangeMapping | null {
    const context = logItem?.detail.context
    if (context?.filters_version !== 2) {
        return isLegacyConfig(change.before) && isLegacyConfig(change.after)
            ? null
            : { description: ['changed the feature flag configuration'] }
    }
    const summaries: ActivityChange[] = context.config_changes ?? []
    const description = summaries.map((summary): string => {
        if (summary.field === 'rule_order') {
            return 'changed the rule order'
        }
        const verb = summary.action === 'created' ? 'added' : summary.action === 'deleted' ? 'removed' : 'changed'
        const [root, id, field] = summary.field?.split('/') ?? []
        if (root === 'rules' && id) {
            if (!field) {
                return `${verb} rule ${id}`
            }
            return `${verb} ${fieldLabels[field] ?? 'configuration'} for rule ${id}`
        }
        return `${verb} the ${fieldLabels[root] ?? 'configuration'}`
    })
    return { description: description.length ? description : ['changed the feature flag configuration'] }
}
