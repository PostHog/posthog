import { useAsyncActions, useValues } from 'kea'
import posthog from 'posthog-js'
import { useState } from 'react'

import { IconCheck, IconPencil, IconX } from '@posthog/icons'
import { LemonButton, LemonSkeleton, LemonTag, LemonTextAreaMarkdown } from '@posthog/lemon-ui'

import { NotFound } from 'lib/components/NotFound'
import { dayjs } from 'lib/dayjs'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { LemonWidget } from 'lib/lemon-ui/LemonWidget/LemonWidget'
import { PersonDisplay } from 'scenes/persons/PersonDisplay'
import { SceneExport } from 'scenes/sceneTypes'

import { UserInterviewType } from '~/types'

import { UserInterviewLogicProps, userInterviewLogic } from './userInterviewLogic'

export const scene: SceneExport<UserInterviewLogicProps> = {
    component: UserInterview,
    logic: userInterviewLogic,
    paramsToProps: ({ params: { id } }) => ({ id }),
}

export function UserInterview(): JSX.Element {
    const { userInterview, userInterviewLoading } = useValues(userInterviewLogic)
    const { updateUserInterview } = useAsyncActions(userInterviewLogic)

    const [summaryInEditing, setSummaryInEditing] = useState<string | null>(null)

    if (userInterviewLoading && !userInterview) {
        return (
            <div className="@container">
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

    if (!userInterview) {
        return <NotFound object="user interview" />
    }

    return (
        <div className="@container">
            <InterviewMetadata interview={userInterview} />
            <div className="grid grid-cols-1 items-start gap-4 @4xl:grid-cols-3">
                <LemonWidget
                    title="Summary"
                    className="col-span-2"
                    actions={
                        summaryInEditing !== null ? (
                            <>
                                <LemonButton
                                    size="xsmall"
                                    icon={<IconX />}
                                    tooltip="Discard changes"
                                    onClick={() => setSummaryInEditing(null)}
                                    disabledReason={userInterviewLoading ? 'Saving…' : undefined}
                                />
                                <LemonButton
                                    size="xsmall"
                                    icon={<IconCheck />}
                                    tooltip="Save"
                                    onClick={() => {
                                        updateUserInterview({ summary: summaryInEditing })
                                            .then(() => {
                                                setSummaryInEditing(null)
                                            })
                                            .catch((e) => posthog.captureException(e))
                                    }}
                                    loading={userInterviewLoading}
                                />
                            </>
                        ) : (
                            <LemonButton
                                size="xsmall"
                                icon={<IconPencil />}
                                onClick={() => setSummaryInEditing(userInterview.summary || '')}
                            />
                        )
                    }
                >
                    {summaryInEditing !== null ? (
                        <LemonTextAreaMarkdown
                            value={summaryInEditing}
                            onChange={(newValue) => setSummaryInEditing(newValue)}
                            className="pb-2 px-3"
                        />
                    ) : (
                        <LemonMarkdown className="p-3">
                            {userInterview.summary || '_No summary available._'}
                        </LemonMarkdown>
                    )}
                </LemonWidget>
                <div className="col-span-1 flex flex-col gap-y-4">
                    <LemonWidget title="Participants">
                        <div className="p-3 flex flex-col gap-y-2">
                            {userInterview.interviewee_emails.map((interviewee_email) => (
                                <PersonDisplay
                                    key={interviewee_email}
                                    person={{
                                        properties: {
                                            email: interviewee_email,
                                        },
                                        distinct_id: interviewee_email,
                                    }}
                                    withIcon
                                />
                            ))}
                        </div>
                    </LemonWidget>
                    <LemonWidget title="Transcript">
                        <LemonMarkdown className="p-3">
                            {userInterview.transcript || '_No transcript available._'}
                        </LemonMarkdown>
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
                <LemonTag className="bg-bg-light">
                    Created: {dayjs(interview.created_at).format('YYYY-MM-DD HH:mm')}
                </LemonTag>
            )}
        </header>
    )
}
