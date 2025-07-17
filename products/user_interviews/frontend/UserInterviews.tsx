import { IconDownload } from '@posthog/icons'
import { LemonButton, LemonTable, LemonTableColumn } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { PhonePairHogs } from 'lib/components/hedgehogs'
import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { createdAtColumn, createdByColumn } from 'lib/lemon-ui/LemonTable/columnUtils'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { MaxTool } from 'scenes/max/MaxTool'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { ProductKey, UserInterviewType } from '~/types'

import { userInterviewsLogic } from './userInterviewsLogic'

export const scene: SceneExport = {
    component: UserInterviews,
    logic: userInterviewsLogic,
}

export function UserInterviews(): JSX.Element {
    const { userInterviews, userInterviewsLoading } = useValues(userInterviewsLogic)

    const { updateHasSeenProductIntroFor } = useActions(userLogic)
    return (
        <>
            <ProductIntroduction
                productName="User interviews"
                productKey={ProductKey.USER_INTERVIEWS}
                thingName="user interview"
                description="Make full use of user interviews by recording them with PostHog."
                customHog={PhonePairHogs}
                isEmpty={!userInterviewsLoading && userInterviews.length === 0}
                actionElementOverride={
                    <LemonButton
                        type="primary"
                        icon={<IconDownload />}
                        onClick={() => updateHasSeenProductIntroFor(ProductKey.USER_INTERVIEWS, true)}
                        to="https://posthog.com/recorder"
                        data-attr="install-recorder"
                    >
                        Install PostHog Recorder
                    </LemonButton>
                }
            />
            <MaxTool
                name="analyze_user_interviews"
                displayName="Analyze user interviews"
                description="Max can summarize user interviews and extract learnings"
                context={{}}
                callback={() => {
                    // No need to handle structured output for this tool
                }}
            >
                <LemonTable
                    loading={userInterviewsLoading}
                    columns={[
                        {
                            title: 'Interviewees',
                            key: 'interviewees',
                            render: (_, row) => (
                                <LemonTableLink
                                    title={row.interviewee_emails.join(', ')}
                                    to={urls.userInterview(row.id)}
                                />
                            ),
                        },
                        createdAtColumn() as LemonTableColumn<UserInterviewType, keyof UserInterviewType | undefined>,
                        createdByColumn() as LemonTableColumn<UserInterviewType, keyof UserInterviewType | undefined>,
                    ]}
                    dataSource={userInterviews}
                    loadingSkeletonRows={5}
                />
            </MaxTool>
        </>
    )
}
