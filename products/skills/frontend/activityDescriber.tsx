import {
    ActivityChange,
    ActivityLogItem,
    ActivityLogUserName,
    HumanizedChange,
    activityLogSummary,
    defaultDescriber,
} from 'lib/components/ActivityLog/humanizeActivity'

interface SkillFilesChange {
    added?: string[]
    removed?: string[]
    edited?: string[]
}

function findChange(logItem: ActivityLogItem, field: string): ActivityChange | undefined {
    return logItem.detail?.changes?.find((change) => change.field === field)
}

function changeAfter(logItem: ActivityLogItem, field: string): string | null {
    const after = findChange(logItem, field)?.after
    return after != null ? String(after) : null
}

function describeFiles(logItem: ActivityLogItem): string | null {
    const files = findChange(logItem, 'files')?.after as SkillFilesChange | undefined
    if (!files) {
        return null
    }
    const parts = [
        files.added?.length ? `added ${files.added.join(', ')}` : null,
        files.removed?.length ? `removed ${files.removed.join(', ')}` : null,
        files.edited?.length ? `edited ${files.edited.join(', ')}` : null,
    ].filter((part): part is string => part !== null)
    return parts.length ? parts.join('; ') : null
}

function describeVersionPublished(logItem: ActivityLogItem, skillName: string): HumanizedChange {
    const version = changeAfter(logItem, 'version')
    const versionDescription = changeAfter(logItem, 'version_description')
    const files = describeFiles(logItem)
    const action = `Published version ${version ?? '?'}${files ? ` (${files})` : ''}`
    return {
        summary: activityLogSummary(logItem, action, skillName, versionDescription ?? undefined),
        description: (
            <>
                <ActivityLogUserName logItem={logItem} /> published version <b>{version ?? '?'}</b> of skill{' '}
                <b>{skillName}</b>
                {files ? <> ({files})</> : null}
                {versionDescription ? <>: "{versionDescription}"</> : null}
            </>
        ),
    }
}

// Scope LLMSkill rows, written by log_skill_activity in products/skills/backend/activity_logging.py.
// detail.name is the skill name at the time of the change.
export function skillActivityDescriber(logItem: ActivityLogItem, asNotification?: boolean): HumanizedChange {
    const skillName = logItem?.detail?.name ?? ''

    if (logItem.activity === 'created') {
        const duplicatedFrom = changeAfter(logItem, 'duplicated_from')
        return {
            summary: activityLogSummary(
                logItem,
                duplicatedFrom ? `Created a copy of ${duplicatedFrom}` : 'Created the skill',
                skillName
            ),
            description: duplicatedFrom ? (
                <>
                    <ActivityLogUserName logItem={logItem} /> created skill <b>{skillName}</b> as a copy of{' '}
                    <b>{duplicatedFrom}</b>
                </>
            ) : (
                <>
                    <ActivityLogUserName logItem={logItem} /> created skill <b>{skillName}</b>
                </>
            ),
        }
    }

    if (logItem.activity === 'deleted') {
        return {
            summary: activityLogSummary(logItem, 'Archived the skill', skillName),
            description: (
                <>
                    <ActivityLogUserName logItem={logItem} /> archived skill <b>{skillName}</b>
                </>
            ),
        }
    }

    if (logItem.activity === 'updated') {
        if (findChange(logItem, 'version')) {
            return describeVersionPublished(logItem, skillName)
        }

        const rename = findChange(logItem, 'name')
        if (rename) {
            return {
                summary: activityLogSummary(logItem, `Renamed the skill from ${String(rename.before)}`, skillName),
                description: (
                    <>
                        <ActivityLogUserName logItem={logItem} /> renamed skill <b>{String(rename.before)}</b> to{' '}
                        <b>{skillName}</b>
                    </>
                ),
            }
        }

        if (findChange(logItem, 'owners')) {
            return {
                summary: activityLogSummary(logItem, 'Changed the owners', skillName),
                description: (
                    <>
                        <ActivityLogUserName logItem={logItem} /> changed the owners of skill <b>{skillName}</b>
                    </>
                ),
            }
        }
    }

    return defaultDescriber(logItem, asNotification, skillName)
}
