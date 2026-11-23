import { Card, CardContent, Item, ItemContent, ItemDescription } from '@posthog/quill'

import { PlatformAlertCreateDestinationApi } from 'products/alerts_platform/frontend/generated/api.schemas'

import { buildLogsAlertReviewItems } from './logsAlertEditorModel'
import { LogsAlertFormType } from './logsAlertFormLogic'

export function QuillLogsAlertReview({
    alertForm,
    pendingDestinations,
    canGroup,
}: {
    alertForm: LogsAlertFormType
    pendingDestinations: PlatformAlertCreateDestinationApi[]
    canGroup: boolean
}): JSX.Element {
    const items = buildLogsAlertReviewItems(alertForm, pendingDestinations, canGroup)

    return (
        <div className="@container flex flex-col gap-3">
            {pendingDestinations.length === 0 ? (
                <Item tone="warning" size="sm">
                    <ItemContent>
                        <ItemDescription>
                            This alert will run without notifications. Go back to Notify to add a destination.
                        </ItemDescription>
                    </ItemContent>
                </Item>
            ) : null}
            <Card size="sm">
                <CardContent>
                    <dl className="m-0 flex flex-col gap-1.5 text-xs">
                        {items.map(({ label, value }) => (
                            <div
                                key={label}
                                className="grid grid-cols-1 gap-1 @md:grid-cols-[13rem_minmax(0,1fr)] @md:gap-2"
                            >
                                <dt className="text-muted-foreground">{label}</dt>
                                <dd className="m-0 font-medium">{value}</dd>
                            </div>
                        ))}
                    </dl>
                </CardContent>
            </Card>
        </div>
    )
}
