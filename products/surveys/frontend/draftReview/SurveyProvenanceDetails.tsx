import { useValues } from 'kea'

import { LemonCollapse, LemonSkeleton } from '@posthog/lemon-ui'

import { UserActivityIndicator } from 'lib/components/UserActivityIndicator/UserActivityIndicator'

import { SURVEY_CHANNEL_LABELS } from './surveyProvenance'
import { surveyProvenanceLogic } from './surveyProvenanceLogic'

export function SurveyProvenanceDetails({ surveyId }: { surveyId: string }): JSX.Element {
    const { provenance } = useValues(surveyProvenanceLogic({ surveyId }))

    if (!provenance) {
        return <LemonSkeleton className="h-4 w-2/3" />
    }

    const { createdBy, createdAt, channel, agentIntent, lastEdit } = provenance
    return (
        <div className="flex flex-col gap-1 text-secondary">
            <UserActivityIndicator
                className="flex-wrap gap-x-1"
                prefix={channel ? `Created through ${SURVEY_CHANNEL_LABELS[channel]}` : 'Created'}
                at={createdAt}
                by={createdBy}
            />
            {lastEdit && (
                <UserActivityIndicator
                    className="flex-wrap gap-x-1"
                    prefix={`Last edited through ${SURVEY_CHANNEL_LABELS[lastEdit.channel]}`}
                    at={lastEdit.at}
                    by={lastEdit.by}
                />
            )}
            {agentIntent && (
                <LemonCollapse
                    size="xsmall"
                    panels={[
                        {
                            key: 'request',
                            header: 'See the stated request',
                            dataAttr: 'survey-draft-provenance-request',
                            content: <p className="m-0 border-l-2 pl-2 text-xs whitespace-pre-wrap">{agentIntent}</p>,
                        },
                    ]}
                />
            )}
        </div>
    )
}
