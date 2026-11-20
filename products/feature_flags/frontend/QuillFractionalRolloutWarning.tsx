import { Button, Item, ItemContent, ItemDescription } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'

import { FeatureFlagGroupType } from '~/types'

import {
    MIN_DOTNET_VERSION,
    MIN_JAVA_VERSION,
    formatPercentage,
    fractionalRolloutPercentages,
} from './FractionalRolloutWarning'

export function QuillFractionalRolloutWarning({
    filterGroups,
}: {
    filterGroups: FeatureFlagGroupType[] | undefined
}): JSX.Element | null {
    const percentages = fractionalRolloutPercentages(filterGroups)
    if (percentages.length === 0) {
        return null
    }

    const formatted = percentages.map(formatPercentage).join(', ')

    return (
        <Item tone="warning" size="sm">
            <ItemContent>
                <ItemDescription>
                    {percentages.length === 1
                        ? `This flag has a fractional rollout percentage (${formatted}).`
                        : `This flag has fractional rollout percentages (${formatted}).`}{' '}
                    The .NET and Java server-side SDKs read rollout percentages as whole numbers before .NET{' '}
                    {MIN_DOTNET_VERSION} and Java {MIN_JAVA_VERSION}. On an older version the flag definitions payload
                    fails to parse, so local evaluation stops working for <strong>every flag in the project</strong> and
                    each evaluation goes to the <code>/flags</code> endpoint instead. Upgrade those SDKs, or change the
                    rollout to a whole number.{' '}
                    <Button
                        variant="link"
                        size="inline"
                        nativeButton={false}
                        render={
                            <LinkPrimitive
                                to="https://posthog.com/docs/feature-flags/local-evaluation"
                                target="_blank"
                            />
                        }
                    >
                        Learn more about local evaluation
                    </Button>
                </ItemDescription>
            </ItemContent>
        </Item>
    )
}
