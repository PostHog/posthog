import { IconCheck, IconPencil, IconX } from '@posthog/icons'
import { LemonButton, LemonSkeleton, LemonTag, LemonTextAreaMarkdown } from '@posthog/lemon-ui'
import { useAsyncActions, useValues } from 'kea'
import { NotFound } from 'lib/components/NotFound'
import { PageHeader } from 'lib/components/PageHeader'
import { dayjs } from 'lib/dayjs'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { LemonWidget } from 'lib/lemon-ui/LemonWidget/LemonWidget'
import posthog from 'posthog-js'
import { useState } from 'react'
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
    const { updateUserInterview } = useAsyncActions(userInterviewLogic)

    const [summaryInEditing, setSummaryInEditing] = useState<string | null>(null)

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

    if (!userInterview) {
        return <NotFound object="user interview" />
    }

    return (
        <div className="@container">
            <PageHeader caption={<InterviewMetadata interview={userInterview} />} />
            <div className="grid grid-cols-1 items-start gap-4 @4xl:grid-cols-3">
                <LemonWidget
                    title="Summary"
                    className="col-span-2"
                    actions={
                        summaryInEditing !== null ? (
                            <>
                                {!userInterviewLoading && (
                                    <LemonButton
                                        size="xsmall"
                                        icon={<IconX />}
                                        tooltip="Cancel"
                                        onClick={() => setSummaryInEditing(null)}
                                    />
                                )}
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
                <LemonWidget title="Transcript" className="col-span-1">
                    <LemonMarkdown className="p-3">
                        {userInterview.transcript || '_No transcript available._'}
                    </LemonMarkdown>
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
