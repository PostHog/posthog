import {
    ActivityLogItem,
    HumanizedChange,
    defaultDescriber,
    userNameForLogItem,
} from 'lib/components/ActivityLog/humanizeActivity'

// Descriptions are plain strings (no JSX): the skills product package doesn't declare
// `react`, so a `.tsx` file using JSX can't resolve `react/jsx-runtime`. `Description`
// accepts `string`, which keeps this describer dependency-free.
export function llmSkillActivityDescriber(logItem: ActivityLogItem, asNotification?: boolean): HumanizedChange {
    const name = logItem?.detail?.name || 'skill'
    const user = userNameForLogItem(logItem)

    // Archiving is a soft delete of every version of the skill, so the backend logs it as `deleted`.
    if (logItem.activity === 'deleted') {
        return { description: `${user} archived skill ${name}` }
    }

    return defaultDescriber(logItem, asNotification, name)
}
