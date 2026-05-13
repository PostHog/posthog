import { IconArrowLeft, IconCalendar, IconPerson, IconSend } from '@posthog/icons'
import { LemonButton, LemonTag, LemonWidget } from '@posthog/lemon-ui'

import { NotFound } from 'lib/components/NotFound'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { FAKE_OUTREACH } from './UserInterview'
import { FAKE_TOPICS } from './UserInterviews'

export interface UserInterviewResponseProps {
    topicId: string
    responseId: string
}

export const scene: SceneExport<UserInterviewResponseProps> = {
    component: UserInterviewResponse,
    paramsToProps: ({ params: { topicId, responseId } }) => ({ topicId, responseId }),
}

export function UserInterviewResponse({ topicId, responseId }: UserInterviewResponseProps): JSX.Element {
    const topic = FAKE_TOPICS.find((t) => t.id === topicId)
    const outreach = FAKE_OUTREACH[topicId] || []
    const record = outreach.find((o) => o.email === decodeURIComponent(responseId))

    if (!topic || !record) {
        return <NotFound object="interview response" />
    }

    return (
        <SceneContent>
            <LemonButton
                type="tertiary"
                size="small"
                icon={<IconArrowLeft />}
                to={urls.userInterview(topicId)}
                className="mb-1 -ml-2"
            >
                All responses
            </LemonButton>
            <SceneTitleSection name={record.name} description={topic.topic} resourceType={{ type: 'user_interview' }} />

            <div className="grid grid-cols-1 gap-4 @container @4xl:grid-cols-3">
                {/* Left column — transcript */}
                <div className="col-span-2 flex flex-col gap-4">
                    {record.learnings && (
                        <LemonWidget title="Key learnings">
                            <div className="p-4">
                                <p className="text-sm mb-0">{record.learnings}</p>
                            </div>
                        </LemonWidget>
                    )}

                    <LemonWidget title="Transcript">
                        {record.transcript ? (
                            <div className="p-4">
                                <LemonMarkdown className="text-sm leading-relaxed">{record.transcript}</LemonMarkdown>
                            </div>
                        ) : (
                            <div className="p-4 text-muted text-center">No transcript available yet.</div>
                        )}
                    </LemonWidget>
                </div>

                {/* Right column — person metadata */}
                <div className="col-span-1 flex flex-col gap-4">
                    <LemonWidget title="Person">
                        <div className="p-4 space-y-3">
                            <div className="flex items-center gap-2">
                                <IconPerson className="text-muted" />
                                <span className="font-medium">{record.name}</span>
                            </div>
                            <div className="flex items-center gap-2">
                                <IconSend className="text-muted" />
                                <span className="text-sm">{record.email}</span>
                            </div>
                            {record.interview_date && (
                                <div className="flex items-center gap-2">
                                    <IconCalendar className="text-muted" />
                                    <span className="text-sm">{record.interview_date}</span>
                                </div>
                            )}
                            <div className="flex items-center gap-2">
                                <StatusBadge status={record.status} />
                            </div>
                        </div>
                    </LemonWidget>

                    <LemonWidget title="PostHog profile">
                        <div className="p-4 space-y-2">
                            <ProfileRow label="First seen" value="2026-04-15" />
                            <ProfileRow label="Last seen" value="2026-05-11" />
                            <ProfileRow label="Total events" value="1,247" />
                            <ProfileRow label="Sessions" value="34" />
                            <ProfileRow label="Country" value="United States" />
                            <ProfileRow label="Browser" value="Chrome 125" />
                            <ProfileRow label="OS" value="macOS 15.4" />
                        </div>
                    </LemonWidget>

                    <LemonWidget title="Interview context">
                        <div className="p-4 space-y-2">
                            <ProfileRow label="Topic" value={topic.topic} />
                            <ProfileRow label="Outreach date" value={record.outreach_date} />
                            {topic.cohort_name && <ProfileRow label="Cohort" value={topic.cohort_name} />}
                        </div>
                    </LemonWidget>
                </div>
            </div>
        </SceneContent>
    )
}

function StatusBadge({ status }: { status: string }): JSX.Element {
    const config: Record<string, { type: 'success' | 'warning' | 'default' | 'danger'; label: string }> = {
        completed: { type: 'success', label: 'Completed' },
        scheduled: { type: 'warning', label: 'Scheduled' },
        emailed: { type: 'default', label: 'Emailed' },
        no_response: { type: 'default', label: 'No response' },
        declined: { type: 'danger', label: 'Declined' },
    }
    const { type, label } = config[status] || { type: 'default' as const, label: status }
    return <LemonTag type={type}>{label}</LemonTag>
}

function ProfileRow({ label, value }: { label: string; value: string }): JSX.Element {
    return (
        <div className="flex justify-between gap-2">
            <span className="text-muted text-sm shrink-0">{label}</span>
            <span className="text-sm font-medium text-right">{value}</span>
        </div>
    )
}
