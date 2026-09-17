import {
    ActivityLogItem,
    ActivityLogUserName,
    HumanizedChange,
    activityLogSummary,
    defaultDescriber,
} from 'lib/components/ActivityLog/humanizeActivity'
import { SentenceList } from 'lib/components/ActivityLog/SentenceList'
import { Link } from 'lib/lemon-ui/Link'
import { isObject } from 'lib/utils/guards'
import { urls } from 'scenes/urls'

import { PersonDisplay } from './components/PersonDisplay'

export function personActivityDescriber(logItem: ActivityLogItem, asNotification?: boolean): HumanizedChange {
    if (logItem.scope != 'Person') {
        console.error('person describer received a non-person activity')
        return { description: null }
    }

    if (logItem.activity === 'deleted') {
        return {
            summary: activityLogSummary(logItem, 'Deleted the person', logItem.detail.name),
            description: (
                <>
                    <ActivityLogUserName logItem={logItem} /> deleted the person: {logItem.detail.name}
                </>
            ),
        }
    }
    if (logItem.activity === 'updated') {
        // you can only update a person's properties and only one at a time in the UI
        // These API property changes are asynchronous via the plugin server.
        // So the API doesn't capture changes, as they couldn't be guaranteed.
        // only report here that a certain user has manually edited properties

        return {
            summary: activityLogSummary(logItem, "Edited the person's properties", logItem.detail.name || 'Person'),
            description: (
                <>
                    <ActivityLogUserName logItem={logItem} /> edited this person's properties
                </>
            ),
        }
    }
    if (logItem.activity === 'people_merged_into') {
        if (logItem.detail.merge?.source) {
            return {
                summary: activityLogSummary(
                    logItem,
                    <SentenceList
                        prefix="Merged"
                        listParts={logItem.detail.merge.source.map((person, index) => (
                            <PersonDisplay key={person.id || person.uuid || index} person={person} />
                        ))}
                        suffix="into this person"
                    />,
                    logItem.detail.name || 'Person'
                ),
                description: (
                    <SentenceList
                        prefix={
                            <>
                                <ActivityLogUserName logItem={logItem} /> merged
                            </>
                        }
                        listParts={logItem.detail.merge.source.flatMap((di, idx) => (
                            <span key={di.id || di.uuid || idx} className="highlighted-activity">
                                <PersonDisplay person={di} />
                            </span>
                        ))}
                        suffix="into this person"
                    />
                ),
            }
        }
    }

    if (logItem.activity === 'split_person') {
        const after = logItem.detail.changes?.[0].after
        const distinctIds = isObject(after) ? after.distinct_ids : undefined

        if (Array.isArray(distinctIds)) {
            const normalizedDistinctIds = distinctIds.filter((id): id is string => typeof id === 'string')
            return {
                summary: activityLogSummary(
                    logItem,
                    <SentenceList
                        prefix="Split the person into"
                        listParts={normalizedDistinctIds.map((distinctId) => (
                            <Link key={distinctId} to={urls.personByDistinctId(distinctId)}>
                                {distinctId}
                            </Link>
                        ))}
                    />,
                    logItem.detail.name || 'Person'
                ),
                description: (
                    <SentenceList
                        prefix={
                            <>
                                <ActivityLogUserName logItem={logItem} /> split this person into
                            </>
                        }
                        listParts={normalizedDistinctIds.map((di) => (
                            <span key={di} className="highlighted-activity">
                                <Link to={urls.personByDistinctId(di)}>{di}</Link>
                            </span>
                        ))}
                    />
                ),
            }
        }
    }

    return defaultDescriber(logItem, asNotification)
}
