import { LemonTag, Spinner } from '@posthog/lemon-ui'
import { LemonSkeleton } from '@posthog/lemon-ui'
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

    if (userInterviewLoading && !userInterview) {
        return (
            <div className="@container">
                <PageHeader caption={<LemonSkeleton.Text className="w-48 h-4" />} />
                <div className="grid grid-cols-1 items-start gap-4 @4xl:grid-cols-3">
                    <LemonWidget title="Summary" className="col-span-2">
                        <div className="space-y-1.5 p-3">
                            <LemonSkeleton.Text className="h-6 w-[20%]" />
                            <LemonSkeleton.Text className="h-3 w-[60%]" />
                            <LemonSkeleton.Text className="h-3 w-[70%]" />
                            <LemonSkeleton.Text className="h-3 w-[80%]" />
                            <LemonSkeleton.Text className="h-3 w-[40%]" />
                            <LemonSkeleton.Text className="h-3 w-[55%]" />
                            <LemonSkeleton.Text className="h-3 w-[65%]" />
                        </div>
                    </LemonWidget>
                    <LemonWidget title="Transcript" className="col-span-1">
                        <div className="space-y-1.5 p-3">
                            <LemonSkeleton.Text className="h-3 w-[80%]" />
                            <LemonSkeleton.Text className="h-3 w-[40%]" />
                            <LemonSkeleton.Text className="h-3 w-[60%]" />
                            <LemonSkeleton.Text className="h-3 w-[70%]" />
                            <LemonSkeleton.Text className="h-3 w-[80%]" />
                            <LemonSkeleton.Text className="h-3 w-[40%]" />
                            <LemonSkeleton.Text className="h-3 w-[60%]" />
                            <LemonSkeleton.Text className="h-3 w-[70%]" />
                        </div>
                    </LemonWidget>
                </div>
            </div>
        )
    }

    if (userInterviewLoading) {
        return <Spinner />
    }

    if (!userInterview) {
        return <NotFound object="user interview" />
    }

    return (
        <div className="@container">
            <PageHeader caption={<InterviewMetadata interview={userInterview} />} />
            <div className="grid grid-cols-1 items-start gap-4 @4xl:grid-cols-3">
                <LemonWidget title="Summary" className="col-span-2">
                    {userInterview.summary ? (
                        <LemonMarkdown className="p-3">{userInterview.summary}</LemonMarkdown>
                    ) : (
                        <div className="text-muted-alt">No summary available.</div>
                    )}
                </LemonWidget>
                <LemonWidget title="Transcript" className="col-span-1">
                    {userInterview.transcript ? (
                        <LemonMarkdown className="p-3">{userInterview.transcript}</LemonMarkdown>
                    ) : (
                        <div className="text-muted-alt p-3">No transcript available.</div>
                    )}
                </LemonWidget>
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
