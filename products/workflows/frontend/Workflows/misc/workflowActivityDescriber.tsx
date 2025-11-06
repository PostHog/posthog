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

                    const added: string[] = []
                    const removed: string[] = []
                    const modified: string[] = []

                    // Find added actions
                    for (const action of actionsAfter) {
                        if (!beforeMap.has(action.id)) {
                            added.push(action.name || action.id)
                        }
                    }

                    // Find removed actions
                    for (const action of actionsBefore) {
                        if (!afterMap.has(action.id)) {
                            removed.push(action.name || action.id)
                        }
                    }

                    // Find modified actions (same id but different content)
                    for (const action of actionsAfter) {
                        const beforeAction = beforeMap.get(action.id)
                        if (beforeAction && JSON.stringify(beforeAction) !== JSON.stringify(action)) {
                            modified.push(action.name || action.id)
                        }
                    }

                    const changesList: string[] = []
                    if (added.length > 0) {
                        changesList.push(`added ${added.length === 1 ? 'action' : 'actions'}: ${added.join(', ')}`)
                    }
                    if (removed.length > 0) {
                        changesList.push(
                            `removed ${removed.length === 1 ? 'action' : 'actions'}: ${removed.join(', ')}`
                        )
                    }
                    if (modified.length > 0) {
                        changesList.push(modified.join(', '))
                    }

                    if (changesList.length > 0) {
                        changes.push({
                            inline: <>updated actions ({changesList.join('; ')})</>,
                            inlist: <>updated actions ({changesList.join('; ')})</>,
                        })
                    } else {
                        changes.push({
                            inline: 'updated actions',
                            inlist: 'updated actions',
                        })
                    }
                    break
                }
                case 'trigger':
                case 'edges':
                case 'variables': {
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
            description:
                changes.length == 1 ? (
                    <>
                        <strong className="ph-no-capture">{name}</strong> {changes[0].inline} the {objectNoun}:{' '}
                        {workflowName}
                    </>
                ) : (
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
