import { LemonButton, LemonTag, Spinner } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { NotFound } from 'lib/components/NotFound'
import { PageHeader } from 'lib/components/PageHeader'
import { dayjs } from 'lib/dayjs'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { LemonWidget } from 'lib/lemon-ui/LemonWidget/LemonWidget'
import { PersonDisplay } from 'scenes/persons/PersonDisplay'
import { SceneExport } from 'scenes/sceneTypes'

import { UserInterviewType } from '~/types'

import { userInterviewLogic } from './userInterviewLogic'

export const scene: SceneExport = {
    component: UserInterview,
    logic: userInterviewLogic,
    paramsToProps: ({ params: { id } }): (typeof userInterviewLogic)['props'] => ({ id }),
}

export function UserInterview(): JSX.Element {
    const { userInterview, userInterviewLoading } = useValues(userInterviewLogic)

    if (userInterviewLoading) {
        return <Spinner />
    }

    if (!userInterview) {
        return <NotFound object="user interview" />
    }

    return (
        <div className="space-y-4">
            <PageHeader
                caption={<InterviewMetadata interview={userInterview} />}
                buttons={
                    <LemonButton type="secondary" to="/user_interviews">
                        Back to list
                    </LemonButton>
                }
            />

            <div className="mt-4 grid grid-cols-1 md:grid-cols-3 gap-4">
                <div className="md:col-span-2 space-y-4">
                    {/* Summary */}
                    <LemonWidget title="Summary">
                        {userInterview.summary ? (
                            <LemonMarkdown className="p-3" lowKeyHeadings>
                                {userInterview.summary}
                            </LemonMarkdown>
                        ) : (
                            <div className="text-muted-alt">No summary available.</div>
                        )}
                    </LemonWidget>
                    <LemonWidget title="Transcript">
                        {userInterview.transcript ? (
                            <LemonMarkdown className="p-3" lowKeyHeadings>
                                {userInterview.transcript}
                            </LemonMarkdown>
                        ) : (
                            <div className="text-muted-alt p-3">No transcript available.</div>
                        )}
                    </LemonWidget>
                </div>

                <div className="space-y-4">
                    <LemonWidget title="Details">
                        <div className="p-3">
                            <p>
                                <strong>ID:</strong> {userInterview.id}
                            </p>
                            {userInterview.created_at && (
                                <p>
                                    <strong>Created At:</strong>{' '}
                                    {dayjs(userInterview.created_at).format('MMMM D, YYYY h:mm A')}
                                </p>
                            )}
                            {userInterview.created_by && (
                                <p>
                                    <strong>Created By:</strong>{' '}
                                    <PersonDisplay
                                        person={{
                                            ...userInterview.created_by,
                                            id: String(userInterview.created_by.id),
                                        }}
                                        withIcon
                                    />
                                </p>
                            )}
                            {userInterview.interviewee_emails && userInterview.interviewee_emails.length > 0 && (
                                <p>
                                    <strong>Interviewees:</strong> {userInterview.interviewee_emails.join(', ')}
                                </p>
                            )}
                        </div>
                    </LemonWidget>

                    <LemonWidget title="Notes / Analysis">
                        <div className="h-48 flex items-center justify-center text-muted-alt p-3">
                            Notes Area (TODO)
                        </div>
                    </LemonWidget>
                </div>
            </div>
        </div>
    )
}

function InterviewMetadata({ interview }: { interview: UserInterviewType }): JSX.Element {
    return (
        <header className="flex gap-x-2 gap-y-1 flex-wrap items-center">
            {interview.created_at && (
                <LemonTag type="default">Created: {dayjs(interview.created_at).format('YYYY-MM-DD HH:mm')}</LemonTag>
            )}
            {interview.created_by && (
                <LemonTag type="default">
                    By:{' '}
                    <PersonDisplay
                        person={{ ...interview.created_by, id: String(interview.created_by.id) }}
                        withIcon={false}
                    />
                </LemonTag>
            )}
            {interview.interviewee_emails && interview.interviewee_emails.length > 0 && (
                <LemonTag type="highlight">Interviewees: {interview.interviewee_emails.join(', ')}</LemonTag>
            )}
        </header>
    )
}
