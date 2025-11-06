import {
    ActivityLogItem,
    HumanizedChange,
    defaultDescriber,
    userNameForLogItem,
} from 'lib/components/ActivityLog/humanizeActivity'
import { Link } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

const nameOrLinkToWorkflow = (id?: string | null, name?: string | null): string | JSX.Element => {
    const displayName = name || '(empty string)'
    return id ? <Link to={urls.workflow(id, 'workflow')}>{displayName}</Link> : displayName
}

export function workflowActivityDescriber(logItem: ActivityLogItem, asNotification?: boolean): HumanizedChange {
    if (logItem.scope != 'HogFlow') {
        console.error('Workflow describer received a non-HogFlow activity')
        return { description: null }
    }

    const objectNoun = 'workflow'

    if (logItem.activity == 'created') {
        return {
            description: (
                <>
                    <strong className="ph-no-capture">{userNameForLogItem(logItem)}</strong> created the {objectNoun}:{' '}
                    {nameOrLinkToWorkflow(logItem?.item_id, logItem?.detail.name)}
                </>
            ),
        }
    }

    if (logItem.activity == 'deleted') {
        return {
            description: (
                <>
                    <strong className="ph-no-capture">{userNameForLogItem(logItem)}</strong> deleted the {objectNoun}:{' '}
                    {logItem.detail.name}
                </>
            ),
        }
    }

    if (logItem.activity == 'updated') {
        const changes: { inline: string | JSX.Element; inlist: string | JSX.Element }[] = []
        for (const change of logItem.detail.changes ?? []) {
            switch (change.field) {
                case 'name': {
                    changes.push({
                        inline: (
                            <>
                                renamed from <strong>{change.before}</strong> to <strong>{change.after}</strong>
                            </>
                        ),
                        inlist: (
                            <>
                                renamed from <strong>{change.before}</strong> to <strong>{change.after}</strong>
                            </>
                        ),
                    })
                    break
                }
                case 'description': {
                    changes.push({
                        inline: 'updated description',
                        inlist: 'updated description',
                    })
                    break
                }
                case 'status': {
                    const statusChange = change.after === 'active' ? 'enabled' : 'disabled'
                    changes.push({
                        inline: statusChange,
                        inlist: `${statusChange} the ${objectNoun}`,
                    })
                    break
                }
                case 'actions': {
                    const actionsBefore = (change.before as any[]) || []
                    const actionsAfter = (change.after as any[]) || []

                    // Create maps by id for easier comparison
                    const beforeMap = new Map(actionsBefore.map((a: any) => [a.id, a]))
                    const afterMap = new Map(actionsAfter.map((a: any) => [a.id, a]))

                    // Find added actions
                    for (const action of actionsAfter) {
                        if (!beforeMap.has(action.id)) {
                            changes.push({
                                inline: <>added action {action.name || action.id}</>,
                                inlist: <>added action {action.name || action.id}</>,
                            })
                        }
                    }

                    // Find removed actions
                    for (const action of actionsBefore) {
                        if (!afterMap.has(action.id)) {
                            changes.push({
                                inline: <>deleted action {action.name || action.id}</>,
                                inlist: <>deleted action {action.name || action.id}</>,
                            })
                        }
                    }

                    // Find modified actions (same id but different content)
                    for (const action of actionsAfter) {
                        const beforeAction = beforeMap.get(action.id)
                        if (beforeAction && JSON.stringify(beforeAction) !== JSON.stringify(action)) {
                            changes.push({
                                inline: <>updated action {action.name || action.id}</>,
                                inlist: <>updated action {action.name || action.id}</>,
                            })
                        }
                    }
                    break
                }
                case 'variables': {
                    const variablesBefore = (change.before as any[]) || []
                    const variablesAfter = (change.after as any[]) || []

                    // Create maps by key for easier comparison
                    const beforeMap = new Map(variablesBefore.map((v: any) => [v.key, v]))
                    const afterMap = new Map(variablesAfter.map((v: any) => [v.key, v]))

                    // Find added variables
                    for (const variable of variablesAfter) {
                        if (!beforeMap.has(variable.key)) {
                            const varName = variable.key || variable.label || 'unnamed'
                            changes.push({
                                inline: <>added variable {varName}</>,
                                inlist: <>added variable {varName}</>,
                            })
                        }
                    }

                    // Find removed variables
                    for (const variable of variablesBefore) {
                        if (!afterMap.has(variable.key)) {
                            const varName = variable.key || variable.label || 'unnamed'
                            changes.push({
                                inline: <>deleted variable {varName}</>,
                                inlist: <>deleted variable {varName}</>,
                            })
                        }
                    }

                    // Find modified variables (same key but different content)
                    for (const variable of variablesAfter) {
                        const beforeVariable = beforeMap.get(variable.key)
                        if (beforeVariable && JSON.stringify(beforeVariable) !== JSON.stringify(variable)) {
                            const varName = variable.key || variable.label || 'unnamed'
                            changes.push({
                                inline: <>updated variable {varName}</>,
                                inlist: <>updated variable {varName}</>,
                            })
                        }
                    }
                    break
                }
                case 'trigger':
                case 'edges': {
                    changes.push({
                        inline: `updated ${change.field}`,
                        inlist: `updated ${change.field}`,
                    })
                    break
                }
                default:
                    changes.push({
                        inline: `updated ${change.field}`,
                        inlist: `updated ${change.field}`,
                    })
            }
        }
        const name = userNameForLogItem(logItem)
        const workflowName = nameOrLinkToWorkflow(logItem?.item_id, logItem?.detail.name)

        return {
            description: (
                <div>
                    <strong className="ph-no-capture">{name}</strong> updated the {objectNoun}: {workflowName}
                    <ul className="ml-5 list-disc">
                        {changes.map((c, i) => (
                            <li key={i}>{c.inlist}</li>
                        ))}
                    </ul>
                </div>
            ),
        }
    }
    return defaultDescriber(logItem, asNotification, nameOrLinkToWorkflow(logItem?.item_id, logItem?.detail.name))
}
