import type { ReactElement } from 'react'

import { DescriptionList, formatDate } from '@posthog/mcp-ui'
import { Badge, Card, CardContent } from '@posthog/quill'

import { SurveyQuestion, type SurveyQuestionData } from './SurveyQuestion'
import { STATUS_VARIANTS, SURVEY_TYPE_LABELS } from './utils'

export interface SurveyData {
    id: string
    name: string
    description?: string | null
    type?: string
    status?: string
    questions?: SurveyQuestionData[]
    conditions?: Record<string, unknown> | null
    start_date?: string | null
    end_date?: string | null
    created_at?: string
    responses_limit?: number | null
    archived?: boolean
    _posthogUrl?: string
}

export interface SurveyViewProps {
    survey: SurveyData
}

export function SurveyView({ survey }: SurveyViewProps): ReactElement {
    const status = survey.status ?? 'draft'

    return (
        <div className="p-4">
            <div className="flex flex-col gap-3">
                <div className="flex flex-col gap-1">
                    <div className="flex items-center gap-2 flex-wrap">
                        <span className="text-lg font-semibold">{survey.name}</span>
                        <Badge variant={STATUS_VARIANTS[status] ?? 'default'}>
                            {status.charAt(0).toUpperCase() + status.slice(1)}
                        </Badge>
                        {survey.type && <Badge>{SURVEY_TYPE_LABELS[survey.type] ?? survey.type}</Badge>}
                    </div>
                    {survey.description && <span className="text-sm text-muted-foreground">{survey.description}</span>}
                </div>

                <Card>
                    <CardContent>
                        <DescriptionList
                            columns={2}
                            items={[
                                ...(survey.start_date
                                    ? [{ label: 'Started', value: formatDate(survey.start_date) }]
                                    : []),
                                ...(survey.end_date ? [{ label: 'Ended', value: formatDate(survey.end_date) }] : []),
                                ...(survey.responses_limit != null
                                    ? [{ label: 'Response limit', value: String(survey.responses_limit) }]
                                    : []),
                                ...(survey.created_at
                                    ? [{ label: 'Created', value: formatDate(survey.created_at) }]
                                    : []),
                            ]}
                        />
                    </CardContent>
                </Card>

                {survey.questions && survey.questions.length > 0 && (
                    <Card>
                        <CardContent>
                            <div className="flex flex-col gap-3">
                                <span className="text-sm font-semibold">Questions ({survey.questions.length})</span>
                                {survey.questions.map((q, i) => (
                                    <div key={i}>
                                        {i > 0 && <div className="border-t -mx-4 mb-3" />}
                                        <SurveyQuestion question={q} index={i} />
                                    </div>
                                ))}
                            </div>
                        </CardContent>
                    </Card>
                )}
            </div>
        </div>
    )
}
