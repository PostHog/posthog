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

type ArrayChangeItem = { id?: string; key?: string; name?: string; label?: string }

function processArrayChanges<T extends ArrayChangeItem>(
    itemsBefore: T[],
    itemsAfter: T[],
    getId: (item: T) => string,
    getName: (item: T) => string,
    itemType: 'action' | 'variable'
): JSX.Element[] {
    const beforeMap = new Map(itemsBefore.map((item) => [getId(item), item]))
    const afterMap = new Map(itemsAfter.map((item) => [getId(item), item]))
    const changes: JSX.Element[] = []

    // Find added items
    for (const item of itemsAfter) {
        const id = getId(item)
        if (id && !beforeMap.has(id)) {
            changes.push(
                <>
                    added {itemType} {getName(item)}
                </>
            )
        }
    }

    // Find removed items
    for (const item of itemsBefore) {
        const id = getId(item)
        if (id && !afterMap.has(id)) {
            changes.push(
                <>
                    deleted {itemType} {getName(item)}
                </>
            )
        }
    }

    // Find modified items (same id but different content)
    for (const item of itemsAfter) {
        const id = getId(item)
        if (id) {
            const beforeItem = beforeMap.get(id)
            if (beforeItem && JSON.stringify(beforeItem) !== JSON.stringify(item)) {
                changes.push(
                    <>
                        updated {itemType} {getName(item)}
                    </>
                )
            }
        }
    }

    return changes
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
        const changes: JSX.Element[] = []
        for (const change of logItem.detail.changes ?? []) {
            switch (change.field) {
                case 'name': {
                    changes.push(
                        <>
                            renamed from <strong>{change.before}</strong> to <strong>{change.after}</strong>
                        </>
                    )
                    break
                }
                case 'description': {
                    changes.push(<>updated description</>)
                    break
                }
                case 'status': {
                    const statusChange = change.after === 'active' ? 'enabled' : 'disabled'
                    changes.push(<>{`${statusChange} the ${objectNoun}`}</>)
                    break
                }
                case 'actions': {
                    const actionsBefore = (change.before as any[]) || []
                    const actionsAfter = (change.after as any[]) || []
                    changes.push(
                        ...processArrayChanges(
                            actionsBefore,
                            actionsAfter,
                            (a) => a.id || '',
                            (a) => a.name || a.id || 'unnamed',
                            'action'
                        )
                    )
                    break
                }
                case 'variables': {
                    const variablesBefore = (change.before as any[]) || []
                    const variablesAfter = (change.after as any[]) || []
                    changes.push(
                        ...processArrayChanges(
                            variablesBefore,
                            variablesAfter,
                            (v) => v.key || '',
                            (v) => v.key || v.label || 'unnamed',
                            'variable'
                        )
                    )
                    break
                }
                case 'trigger':
                case 'edges': {
                    changes.push(<>updated {change.field}</>)
                    break
                }
                default:
                    changes.push(<>updated {change.field}</>)
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
                            <li key={i}>{c}</li>
                        ))}
                    </ul>
                </div>
            ),
        }
    }
    return defaultDescriber(logItem, asNotification, nameOrLinkToWorkflow(logItem?.item_id, logItem?.detail.name))
}
