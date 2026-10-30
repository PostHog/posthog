import { Meta, StoryObj } from '@storybook/react'
import { useMountedLogic } from 'kea'
import { useLayoutEffect } from 'react'

import { mswDecorator } from '~/mocks/browser'
import { NodeKind } from '~/queries/schema/schema-general'

import { SuppressSimilarIssuesDialog } from './SuppressSimilarIssuesDialog'
import { suppressSimilarIssuesLogic } from './suppressSimilarIssuesLogic'
import { SuppressedIssueSnapshot, SuppressionEventFilter } from './suppressSimilarScopes'

const IMPACT_BY_MESSAGE_OPERATOR: Record<string, [exceptions: number, issues: number]> = {
    exact: [40, 1],
    regex: [71, 3],
}

const SUPPRESSED_ISSUES: SuppressedIssueSnapshot[] = [
    { id: 'http-503', exceptionType: 'Error', exceptionMessage: 'Request failed with status code 503' },
]

function OpenDialog(): JSX.Element {
    const logic = useMountedLogic(suppressSimilarIssuesLogic)
    useLayoutEffect(() => {
        logic.actions.openSuggestion(SUPPRESSED_ISSUES)
    }, [logic])
    return <SuppressSimilarIssuesDialog />
}

const meta: Meta = {
    title: 'Scenes-App/ErrorTracking/Suppress similar issues dialog',
    parameters: { layout: 'fullscreen', viewMode: 'story' },
    decorators: [
        mswDecorator({
            post: {
                '/api/environments/:team_id/query/:kind/': async ({ request }) => {
                    const body = (await request.json()) as {
                        query?: { kind?: string; fixedProperties?: { values: SuppressionEventFilter[] }[] }
                    }
                    const messageFilter = body.query?.fixedProperties?.[0]?.values.find(
                        (filter) => filter.key === '$exception_values'
                    )
                    const impact = messageFilter?.operator ? IMPACT_BY_MESSAGE_OPERATOR[messageFilter.operator] : null
                    return [200, { results: body.query?.kind === NodeKind.EventsQuery && impact ? [impact] : [] }]
                },
            },
        }),
    ],
}
export default meta

type Story = StoryObj<{}>

export const SimilarMessages: Story = { render: () => <OpenDialog /> }
