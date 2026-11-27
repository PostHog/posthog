import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { IconChevronDown, IconPlus } from '@posthog/icons'
import {
    Button,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
} from '@posthog/quill'

import { urls } from 'scenes/urls'

import { RELEASE_ALL_TYPE_INFO } from './releaseAllTypeInfo'
import { releaseLogic } from './releaseLogic'

export function ReleaseAllNewMenu(): JSX.Element {
    const { canEditReleases, releasesEnabled } = useValues(releaseLogic)
    const { setNewReleaseOpen } = useActions(releaseLogic)
    const icon = (type: keyof typeof RELEASE_ALL_TYPE_INFO): JSX.Element => (
        // eslint-disable-next-line react/forbid-dom-props
        <span className="flex items-center" style={{ color: RELEASE_ALL_TYPE_INFO[type].color }}>
            {RELEASE_ALL_TYPE_INFO[type].icon}
        </span>
    )
    return (
        <DropdownMenu>
            <DropdownMenuTrigger render={<Button variant="primary" data-attr="release-all-new" />}>
                <IconPlus />
                New
                <IconChevronDown />
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
                {releasesEnabled && (
                    <>
                        <DropdownMenuItem
                            disabledReason={
                                canEditReleases
                                    ? undefined
                                    : 'You need editor access to feature flags to create a release.'
                            }
                            onClick={() => setNewReleaseOpen(true)}
                            data-attr="release-all-new-release"
                        >
                            {icon('release')}
                            Release
                        </DropdownMenuItem>
                        <DropdownMenuSeparator />
                    </>
                )}
                <DropdownMenuItem
                    onClick={() => router.actions.push(urls.featureFlag('new'))}
                    data-attr="release-all-new-flag"
                >
                    {icon('feature_flag')}
                    Feature flag
                </DropdownMenuItem>
                <DropdownMenuItem
                    onClick={() => router.actions.push(urls.experiment('new'))}
                    data-attr="release-all-new-experiment"
                >
                    {icon('experiment')}
                    Experiment
                </DropdownMenuItem>
                <DropdownMenuItem
                    onClick={() => router.actions.push(urls.earlyAccessFeature('new'))}
                    data-attr="release-all-new-early-access"
                >
                    {icon('early_access_feature')}
                    Early access feature
                </DropdownMenuItem>
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
