import { useActions, useValues } from 'kea'

import { IconPlus } from '@posthog/icons'
import {
    Button,
    Card,
    CardContent,
    Heading,
    Item,
    ItemActions,
    ItemContent,
    ItemDescription,
    ItemTitle,
    Progress,
    ProgressLabel,
    Text,
} from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { ReleaseLifecycle } from './ReleaseLifecycle'
import { ReleaseLinkFlagCombobox } from './ReleaseLinkFlagCombobox'
import { releaseLogic } from './releaseLogic'
import { REVIEW_AFTER_DAYS, ReleaseRow, STAGE_COLOR } from './releaseUtils'

export function ReleaseStatusCard({ row }: { row: ReleaseRow }): JSX.Element {
    const { canEditReleases } = useValues(releaseLogic)
    const { openSchedule } = useActions(releaseLogic)
    const step = row.nextStep

    return (
        <Card data-attr="release-status">
            <CardContent className="flex flex-col gap-5">
                <ReleaseLifecycle steps={row.lifecycle} color={STAGE_COLOR[row.stage]} />
                <div className="flex flex-col gap-1">
                    <Heading size="lg" render={<h2 className="m-0" />}>
                        {row.headline}
                    </Heading>
                    {row.detail && (
                        <Text size="xs" variant="muted" render={<p className="m-0" />}>
                            {row.detail}
                        </Text>
                    )}
                </div>
                {row.runningDays > 0 && row.runningDays < REVIEW_AFTER_DAYS && (
                    <Progress value={(row.runningDays / REVIEW_AFTER_DAYS) * 100} className="max-w-md">
                        <ProgressLabel>Toward two weeks of data</ProgressLabel>
                        <Text size="xs" variant="muted" className="ms-auto">
                            {`${row.runningDays} of ${REVIEW_AFTER_DAYS} days`}
                        </Text>
                    </Progress>
                )}
                {step ? (
                    <Item
                        variant="outline"
                        tone={row.needsDecision ? 'info' : 'default'}
                        data-attr="release-next-step-callout"
                    >
                        <ItemContent>
                            <ItemTitle>{`Next: ${step.title.charAt(0).toLowerCase()}${step.title.slice(1)}`}</ItemTitle>
                            <ItemDescription>{step.detail}</ItemDescription>
                        </ItemContent>
                        <ItemActions className="flex-wrap">
                            {!row.flags.length && canEditReleases && (
                                <>
                                    <div className="w-56">
                                        <ReleaseLinkFlagCombobox row={row} placeholder="Find a flag" />
                                    </div>
                                    <Button
                                        variant="outline"
                                        nativeButton={false}
                                        render={<LinkPrimitive to={urls.featureFlag('new')} />}
                                        data-attr="release-create-flag"
                                    >
                                        <IconPlus />
                                        Create a flag
                                    </Button>
                                </>
                            )}
                            {step.secondaryLabel && step.secondaryTo && (
                                <Button
                                    variant="outline"
                                    nativeButton={false}
                                    render={<LinkPrimitive to={step.secondaryTo} />}
                                    data-attr="release-next-step-secondary"
                                >
                                    {step.secondaryLabel}
                                </Button>
                            )}
                            {step.label && (
                                <Button
                                    variant={step.urgent ? 'primary' : 'outline'}
                                    {...(step.scheduleFlagId !== undefined
                                        ? { onClick: () => openSchedule(step.scheduleFlagId as number) }
                                        : { nativeButton: false, render: <LinkPrimitive to={step.to ?? ''} /> })}
                                    data-attr="release-next-step"
                                >
                                    {step.label}
                                </Button>
                            )}
                        </ItemActions>
                    </Item>
                ) : (
                    <Text size="xs" variant="muted">
                        Nothing needs a decision right now.
                    </Text>
                )}
            </CardContent>
        </Card>
    )
}
