import { IconOpenSidebar } from '@posthog/icons'
import { LemonButton, Link } from '@posthog/lemon-ui'
import { Button, Empty, EmptyContent, EmptyDescription, EmptyHeader, EmptyTitle } from '@posthog/quill'

import { PayGateMini } from 'lib/components/PayGateMini/PayGateMini'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { useQuillSurface } from 'lib/ui/QuillSurface/quillSurfaceContext'

import { AvailableFeature } from '~/types'

const GROUPS_LEARN_MORE_URL = `https://posthog.com/docs/user-guides/group-analytics?utm_medium=in-product&utm_campaign=${AvailableFeature.GROUP_ANALYTICS}-upgrade-learn-more`

export function GroupsIntroduction(): JSX.Element {
    const quillSurface = useQuillSurface()

    return (
        <PayGateMini
            feature={AvailableFeature.GROUP_ANALYTICS}
            featureDetail="groups-introduction"
            className="py-8"
            docsLink="https://posthog.com/docs/user-guides/group-analytics"
        >
            {quillSurface ? (
                <Empty className="min-h-56 rounded-lg border border-border py-8">
                    <EmptyHeader>
                        <EmptyTitle>Start tracking groups</EmptyTitle>
                        <EmptyDescription>
                            Get a 360&deg; view of how companies or teams use your product. Use the SDK to create a
                            group, and then include the group identifier in the event&nbsp;properties.
                        </EmptyDescription>
                    </EmptyHeader>
                    <EmptyContent>
                        <Button
                            variant="primary"
                            nativeButton={false}
                            render={<LinkPrimitive to={GROUPS_LEARN_MORE_URL} target="_blank" />}
                            data-attr={`${AvailableFeature.GROUP_ANALYTICS}-learn-more`}
                        >
                            Learn more
                            <IconOpenSidebar />
                        </Button>
                    </EmptyContent>
                </Empty>
            ) : (
                <div className="flex flex-col items-center mt-4 justify-center text-center border rounded-lg py-8 min-h-56">
                    <h2 className="mb-2 text-2xl font-semibold">Start tracking groups</h2>
                    <div className="max-w-140">
                        Get a 360&deg; view of how companies or teams use your product. Use the SDK to create a group,
                        and then include the group identifier in the event&nbsp;properties.
                    </div>
                    <div className="w-80 max-w-[90%] mt-4">
                        <LemonButton
                            type="primary"
                            to={GROUPS_LEARN_MORE_URL}
                            targetBlank
                            center
                            data-attr={`${AvailableFeature.GROUP_ANALYTICS}-learn-more`}
                        >
                            Learn more <IconOpenSidebar className="ml-4" />
                        </LemonButton>
                    </div>
                </div>
            )}
        </PayGateMini>
    )
}

export function GroupIntroductionFooter({ needsUpgrade }: { needsUpgrade: boolean }): JSX.Element {
    return (
        <div className="text-sm bg-primary rounded p-2 max-w-60">
            {needsUpgrade ? (
                <>
                    Track usage of groups of users with Group&nbsp;Analytics.{' '}
                    <Link
                        className="font-medium"
                        to="/organization/billing"
                        target="_blank"
                        data-attr="group-analytics-upgrade"
                    >
                        Upgrade now
                    </Link>{' '}
                    or{' '}
                    <Link
                        className="font-medium"
                        to="https://posthog.com/docs/user-guides/group-analytics?utm_medium=in-product&utm_campaign=group-analytics-learn-more"
                        target="_blank"
                        data-attr="group-analytics-learn-more"
                    >
                        learn more
                    </Link>
                    .
                </>
            ) : (
                <>
                    You can now use Group Analytics. See{' '}
                    <Link
                        className="font-medium"
                        to="https://posthog.com/docs/product-analytics/group-analytics?utm_medium=in-product&utm_campaign=group-analytics-get-started"
                        target="_blank"
                        data-attr="group-analytics-get-started"
                    >
                        how to get started
                    </Link>
                    .
                </>
            )}
        </div>
    )
}
