import { useValues } from 'kea'
import { useEffect, useState } from 'react'

import { IconArrowLeft, IconCalendar, IconPerson, IconSend, IconShare } from '@posthog/icons'
import { LemonButton, LemonSkeleton, LemonTag, LemonWidget } from '@posthog/lemon-ui'

import api from 'lib/api'
import { NotFound } from 'lib/components/NotFound'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { Link } from 'lib/lemon-ui/Link'
import { PersonDisplay } from 'scenes/persons/PersonDisplay'
import { SceneExport } from 'scenes/sceneTypes'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { PersonType } from '~/types'

import { userInterviewTopicsRetrieve, userInterviewTopicsIntervieweesList, userInterviewsList } from './generated/api'
import type { UserInterviewTopicApi, IntervieweeContextApi, UserInterviewApi } from './generated/api.schemas'
import { InterviewLinkCopyButton } from './InterviewLinkCopyButton'
import { TranscriptChat } from './TranscriptChat'
import { userInterviewLogic } from './userInterviewLogic'

export interface UserInterviewResponseProps {
    topicId: string
    responseId: string
}

export const scene: SceneExport<UserInterviewResponseProps> = {
    component: UserInterviewResponse,
    paramsToProps: ({ params: { topicId, responseId } }) => ({ topicId, responseId }),
}

export function UserInterviewResponse({ topicId, responseId }: UserInterviewResponseProps): JSX.Element {
    const identifier = decodeURIComponent(responseId)
    const { linkForIdentifier, linksLoading, linksLoadFailed } = useValues(userInterviewLogic({ id: topicId }))
    const interviewUrl = linkForIdentifier(identifier)
    const [loading, setLoading] = useState(true)
    const [topic, setTopic] = useState<UserInterviewTopicApi | null>(null)
    const [intervieweeContext, setIntervieweeContext] = useState<IntervieweeContextApi | null>(null)
    const [interview, setInterview] = useState<UserInterviewApi | null>(null)
    const [person, setPerson] = useState<PersonType | null>(null)

    useEffect(() => {
        const projectId = String(teamLogic.values.currentTeamId)

        async function load(): Promise<void> {
            setLoading(true)
            try {
                const [topicData, intervieweesData, interviewsData] = await Promise.all([
                    userInterviewTopicsRetrieve(projectId, topicId),
                    userInterviewTopicsIntervieweesList(projectId, topicId),
                    userInterviewsList(projectId),
                ])
                setTopic(topicData)
                const ctx = intervieweesData.results.find((c) => c.interviewee_identifier === identifier)
                setIntervieweeContext(ctx || null)
                const matchingInterviews = interviewsData.results.filter(
                    (i) => i.topic === topicId && i.interviewee_identifier === identifier
                )
                // Prefer the interview that has a transcript
                const matchingInterview = matchingInterviews.find((i) => i.transcript) || matchingInterviews[0] || null
                setInterview(matchingInterview)

                // Look up person by email/distinct_id
                try {
                    const personResponse = await api.persons.list({ search: identifier })
                    if (personResponse.results.length > 0) {
                        setPerson(personResponse.results[0])
                    }
                } catch {
                    // Person lookup is best-effort
                }
            } catch {
                setTopic(null)
            } finally {
                setLoading(false)
            }
        }

        void load()
    }, [topicId, identifier])

    if (loading) {
        return (
            <SceneContent>
                <div className="space-y-4">
                    <LemonSkeleton.Text className="h-8 w-[40%]" />
                    <LemonSkeleton.Text className="h-4 w-[30%]" />
                    <LemonSkeleton className="h-48" />
                </div>
            </SceneContent>
        )
    }

    if (!topic) {
        return <NotFound object="interview response" />
    }

    const hasResponse = !!(interview?.transcript || interview?.summary)
    const displayName = person?.properties?.name || person?.properties?.email || person?.name || identifier

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
            <SceneTitleSection name={displayName} description={topic.topic} resourceType={{ type: 'user_interview' }} />

            <div className="grid grid-cols-1 gap-4 @container @4xl:grid-cols-3">
                {/* Left column — transcript + summary */}
                <div className="col-span-2 flex flex-col gap-4">
                    {interview?.summary && (
                        <LemonWidget title="Summary">
                            <div className="p-4">
                                <LemonMarkdown className="text-sm">{interview.summary}</LemonMarkdown>
                            </div>
                        </LemonWidget>
                    )}

                    <LemonWidget title="Transcript">
                        {interview?.transcript ? (
                            <div className="p-4">
                                <TranscriptChat
                                    transcript={interview.transcript}
                                    person={person}
                                    identifier={identifier}
                                />
                            </div>
                        ) : (
                            <div className="p-4 text-muted text-center">
                                No transcript available yet. The interview may not have been completed.
                            </div>
                        )}
                    </LemonWidget>
                </div>

                {/* Right column — metadata */}
                <div className="col-span-1 flex flex-col gap-4">
                    {/* Person card */}
                    <LemonWidget title="Person">
                        <div className="p-4 space-y-3">
                            {person ? (
                                <>
                                    <PersonDisplay person={person} withIcon />
                                    <div className="space-y-2 mt-2">
                                        {person.properties?.email && (
                                            <div className="flex items-center gap-2">
                                                <IconSend className="text-muted shrink-0" />
                                                <span className="text-sm">{person.properties.email}</span>
                                            </div>
                                        )}
                                        {person.created_at && (
                                            <div className="flex items-center gap-2">
                                                <IconCalendar className="text-muted shrink-0" />
                                                <span className="text-sm">
                                                    First seen {person.created_at.split('T')[0]}
                                                </span>
                                            </div>
                                        )}
                                    </div>
                                </>
                            ) : (
                                <div className="flex items-center gap-2">
                                    <IconPerson className="text-muted" />
                                    <span className="font-medium">{identifier}</span>
                                </div>
                            )}
                            <div className="space-y-1">
                                <div className="flex items-center gap-2">
                                    <IconShare className="text-muted shrink-0" />
                                    <span className="text-sm">Interview link</span>
                                    <InterviewLinkCopyButton identifier={identifier} topicId={topicId} />
                                </div>
                                {interviewUrl ? (
                                    <Link
                                        to={interviewUrl}
                                        target="_blank"
                                        className="block text-xs font-mono break-all pl-6"
                                    >
                                        {interviewUrl}
                                    </Link>
                                ) : (
                                    <span className="block text-xs text-muted pl-6">
                                        {linksLoadFailed
                                            ? "Couldn't generate link — refresh to retry"
                                            : linksLoading
                                              ? 'Generating link…'
                                              : 'No link available'}
                                    </span>
                                )}
                            </div>
                            <div>
                                <LemonTag type={hasResponse ? 'success' : 'default'}>
                                    {hasResponse ? 'Responded' : 'Awaiting response'}
                                </LemonTag>
                            </div>
                        </div>
                    </LemonWidget>

                    {intervieweeContext && (
                        <LemonWidget title="Interviewee context">
                            <div className="p-4">
                                <p className="text-sm mb-0">{intervieweeContext.agent_context}</p>
                            </div>
                        </LemonWidget>
                    )}

                    <LemonWidget title="Topic details">
                        <div className="p-4 space-y-2">
                            <DetailRow label="Topic" value={topic.topic} />
                            <DetailRow label="Created" value={topic.created_at.split('T')[0]} />
                        </div>
                    </LemonWidget>
                </div>
            </div>
        </SceneContent>
    )
}

function DetailRow({ label, value }: { label: string; value: string }): JSX.Element {
    return (
        <div className="flex justify-between gap-2">
            <span className="text-muted text-sm shrink-0">{label}</span>
            <span className="text-sm font-medium text-right">{value}</span>
        </div>
    )
}
