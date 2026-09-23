import {
    ActivityChange,
    ActivityLogItem,
    ActivityLogUserName,
    HumanizedChange,
    activityLogSummary,
    defaultDescriber,
} from 'lib/components/ActivityLog/humanizeActivity'
import { SentenceList } from 'lib/components/ActivityLog/SentenceList'
import { Link } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

const nameOrLinkToWorkflow = (id?: string | null, name?: string | null): string | JSX.Element => {
    const displayName = name || '(empty string)'
    return id ? <Link to={urls.workflow(id, 'workflow')}>{displayName}</Link> : displayName
}

type ArrayChangeItem = { id?: string; key?: string; name?: string; label?: string }

// Activity-log values are only diffable per item when they really are arrays. `actions` is masked
// server-side (the graph can carry secret function inputs), so those entries hold the string
// 'masked' rather than a list. Returns null for anything undiffable, so callers can fall back.
function asItemArray(value: unknown): ArrayChangeItem[] | null {
    if (value == null) {
        return []
    }
    return Array.isArray(value) ? (value as ArrayChangeItem[]) : null
}

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

function describeWorkflowItems(change: ActivityChange, itemType: 'action' | 'variable'): JSX.Element[] {
    const before = asItemArray(change.before)
    const after = asItemArray(change.after)
    if (!before || !after) {
        return [<>updated {change.field}</>]
    }
    return itemType === 'action'
        ? processArrayChanges(
              before,
              after,
              (item) => item.id || '',
              (item) => item.name || item.id || 'unnamed',
              itemType
          )
        : processArrayChanges(
              before,
              after,
              (item) => item.key || '',
              (item) => item.key || item.label || 'unnamed',
              itemType
          )
}

function describeWorkflowField(change: ActivityChange): JSX.Element[] {
    switch (change.field) {
        case 'name':
            return [
                <>
                    renamed from <strong>{String(change.before)}</strong> to <strong>{String(change.after)}</strong>
                </>,
            ]
        case 'description':
            return [<>updated description</>]
        case 'status':
            return [<>{`${change.after === 'active' ? 'enabled' : 'disabled'} the workflow`}</>]
        case 'actions':
            return describeWorkflowItems(change, 'action')
        case 'variables':
            return describeWorkflowItems(change, 'variable')
        default:
            return [<>updated {change.field}</>]
    }
}

function describeWorkflowUpdate(logItem: ActivityLogItem): HumanizedChange {
    const objectNoun = 'workflow'
    const verb = logItem.activity == 'published' ? 'published' : 'updated'
    const changes: JSX.Element[] = []
    let preview: string | undefined
    for (const change of logItem.detail.changes ?? []) {
        if (change.field === 'description') {
            preview = typeof change.after === 'string' ? change.after : undefined
        }
        changes.push(...describeWorkflowField(change))
    }
    const workflowName = nameOrLinkToWorkflow(logItem?.item_id, logItem?.detail.name)

    return {
        summary: activityLogSummary(
            logItem,
            <SentenceList
                listParts={
                    logItem.activity === 'published'
                        ? [`Published the ${objectNoun}`, ...changes]
                        : changes.length
                          ? changes
                          : [`Updated the ${objectNoun}`]
                }
            />,
            workflowName,
            preview
        ),
        description: (
            <div>
                <ActivityLogUserName logItem={logItem} /> {verb} the {objectNoun}: {workflowName}
                <ul className="ml-5 list-disc">
                    {changes.map((c, i) => (
                        <li key={i}>{c}</li>
                    ))}
                </ul>
            </div>
        ),
    }
}

export function workflowActivityDescriber(logItem: ActivityLogItem, asNotification?: boolean): HumanizedChange {
    if (logItem.scope != 'HogFlow') {
        console.error('Workflow describer received a non-HogFlow activity')
        return { description: null }
    }

    const objectNoun = 'workflow'

    if (logItem.activity == 'created') {
        return {
            summary: activityLogSummary(
                logItem,
                'Created the workflow',
                nameOrLinkToWorkflow(logItem.item_id, logItem.detail.name)
            ),
            description: (
                <>
                    <ActivityLogUserName logItem={logItem} /> created the {objectNoun}:{' '}
                    {nameOrLinkToWorkflow(logItem?.item_id, logItem?.detail.name)}
                </>
            ),
        }
    }

    if (logItem.activity == 'deleted') {
        return {
            summary: activityLogSummary(logItem, 'Deleted the workflow', logItem.detail.name || 'Workflow'),
            description: (
                <>
                    <ActivityLogUserName logItem={logItem} /> deleted the {objectNoun}: {logItem.detail.name}
                </>
            ),
        }
    }

    if (logItem.activity == 'revision_restored') {
        return {
            summary: activityLogSummary(
                logItem,
                'Staged an earlier version for review',
                nameOrLinkToWorkflow(logItem.item_id, logItem.detail.name)
            ),
            description: (
                <>
                    <ActivityLogUserName logItem={logItem} /> restored a past version into the staged draft of the{' '}
                    {objectNoun}: {nameOrLinkToWorkflow(logItem?.item_id, logItem?.detail.name)}
                </>
            ),
        }
    }

    if (logItem.activity == 'draft_discarded') {
        return {
            summary: activityLogSummary(
                logItem,
                'Discarded the staged draft',
                nameOrLinkToWorkflow(logItem.item_id, logItem.detail.name)
            ),
            description: (
                <>
                    <ActivityLogUserName logItem={logItem} /> discarded the staged draft of the {objectNoun}:{' '}
                    {nameOrLinkToWorkflow(logItem?.item_id, logItem?.detail.name)}
                </>
            ),
        }
    }

    if (logItem.activity == 'email_sending_resumed') {
        return {
            summary: activityLogSummary(
                logItem,
                'Resumed email sending',
                nameOrLinkToWorkflow(logItem.item_id, logItem.detail.name)
            ),
            description: (
                <>
                    <ActivityLogUserName logItem={logItem} /> resumed email sending for the {objectNoun}:{' '}
                    {nameOrLinkToWorkflow(logItem?.item_id, logItem?.detail.name)}
                </>
            ),
        }
    }

    if (logItem.activity == 'updated' || logItem.activity == 'published') {
        return describeWorkflowUpdate(logItem)
    }
    return defaultDescriber(logItem, asNotification, nameOrLinkToWorkflow(logItem?.item_id, logItem?.detail.name))
}
