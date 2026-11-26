import { IconPiggyBank, IconPlus } from '@posthog/icons'
import { Button, Empty, EmptyContent, EmptyHeader, EmptyTitle, IconStack, IconStackItem, Text } from '@posthog/quill'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { LinkPrimitive } from 'lib/lemon-ui/Link'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

export interface QuillRevenueSourcesEmptyProps {
    onAddEvent: () => void
    onImportFromDataWarehouse: () => void
}

export function QuillRevenueSourcesEmpty({
    onAddEvent,
    onImportFromDataWarehouse,
}: QuillRevenueSourcesEmptyProps): JSX.Element {
    return (
        <Empty className="rounded-md border border-border" data-attr="product-introduction-revenue source">
            <EmptyHeader>
                <IconStack>
                    <IconStackItem color="var(--color-product-revenue-analytics-light)">
                        <IconPiggyBank />
                    </IconStackItem>
                </IconStack>
                <EmptyTitle>Create your first revenue source</EmptyTitle>
            </EmptyHeader>
            <EmptyContent>
                <div className="flex flex-wrap justify-center gap-2">
                    <AccessControlAction
                        resourceType={AccessControlResourceType.RevenueAnalytics}
                        minAccessLevel={AccessControlLevel.Editor}
                    >
                        <Button variant="primary" onClick={onAddEvent} data-attr="create-revenue-event">
                            <IconPlus />
                            Add revenue event
                        </Button>
                    </AccessControlAction>
                    <AccessControlAction
                        resourceType={AccessControlResourceType.RevenueAnalytics}
                        minAccessLevel={AccessControlLevel.Editor}
                    >
                        <Button
                            variant="outline"
                            onClick={onImportFromDataWarehouse}
                            data-attr="import-revenue-data-warehouse-tables"
                        >
                            <IconPlus />
                            Import revenue data from data warehouse
                        </Button>
                    </AccessControlAction>
                </div>
                <Text size="xs" variant="muted" render={<p className="m-0" />}>
                    Only Stripe is supported currently.{' '}
                    <Button variant="link" size="inline" render={<LinkPrimitive to="https://posthog.com/roadmap" />}>
                        Request more revenue integrations.
                    </Button>
                </Text>
            </EmptyContent>
        </Empty>
    )
}
