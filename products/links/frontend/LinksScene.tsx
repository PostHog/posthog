import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { IconPlus } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonTable, LemonTableColumn, Link } from '@posthog/lemon-ui'

import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { LemonMenuOverlay } from 'lib/lemon-ui/LemonMenu/LemonMenu'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { createdAtColumn, createdByColumn } from 'lib/lemon-ui/LemonTable/columnUtils'
import stringWithWBR from 'lib/utils/stringWithWBR'
import { Scene, SceneExport } from 'scenes/sceneTypes'
import { sceneConfigurations } from 'scenes/scenes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'
import { LinkType } from '~/types'

import { LinkMetricSparkline } from './LinkMetricSparkline'
import { linksLogic } from './linksLogic'

export const scene: SceneExport = {
    component: LinksScene,
    logic: linksLogic,
}

export function LinksScene(): JSX.Element {
    const { links, linksLoading } = useValues(linksLogic)
    const { deleteLink } = useActions(linksLogic)
    const shouldShowEmptyState = links.length == 0 && !linksLoading

    const columns = [
        {
            title: 'Key',
            sticky: true,
            width: '40%',
            render: function Render(_: any, record: LinkType) {
                return (
                    <LemonTableLink
                        to={record.id ? urls.link(record.id) : undefined}
                        title={
                            <>
                                <span>
                                    {stringWithWBR(record?.short_link_domain + '/' + record?.short_code || '', 17)}
                                </span>
                            </>
                        }
                        description={record?.redirect_url}
                    />
                )
            },
        },
        createdByColumn<LinkType>() as LemonTableColumn<LinkType, keyof LinkType | undefined>,
        createdAtColumn<LinkType>() as LemonTableColumn<LinkType, keyof LinkType | undefined>,
        {
            title: 'Last 7 days',
            render: function RenderLinkMetricSparkline(_: any, link: LinkType) {
                return (
                    // TODO: Update URL to link to page with all `$link_clicked` events
                    // for this specific link
                    <Link to="/insights">
                        <LinkMetricSparkline id={link.hog_function_id ?? link.id} />
                    </Link>
                )
            },
        },
        {
            width: 0,
            render: function Render(_: any, link: LinkType) {
                return (
                    <More
                        overlay={
                            <LemonMenuOverlay
                                items={[
                                    {
                                        label: 'Edit link',
                                        onClick: () => router.actions.push(urls.link(link.id)),
                                    },
                                    {
                                        label: 'Delete link',
                                        status: 'danger' as const,
                                        onClick: () => {
                                            LemonDialog.open({
                                                title: 'Permanently delete link?',
                                                description:
                                                    'Doing so will remove the link and the existing redirect rules. You will NOT lose access to the `$link_clicked` events.',
                                                primaryButton: {
                                                    children: 'Delete',
                                                    type: 'primary',
                                                    status: 'danger',
                                                    'data-attr': 'confirm-delete-link',
                                                    onClick: () => {
                                                        deleteLink(link.id)
                                                    },
                                                },
                                                secondaryButton: {
                                                    children: 'Close',
                                                    type: 'secondary',
                                                },
                                            })
                                        },
                                    },
                                ]}
                            />
                        }
                    />
                )
            },
        },
    ]

    return (
        <SceneContent>
            <SceneTitleSection
                name={sceneConfigurations[Scene.Links].name}
                description={sceneConfigurations[Scene.Links].description}
                resourceType={{
                    type: sceneConfigurations[Scene.Links].iconType || 'default_icon_type',
                }}
                actions={
                    <LemonButton
                        type="primary"
                        icon={<IconPlus />}
                        onClick={() => router.actions.push(urls.link('new'))}
                        size="small"
                        sideAction={{
                            dropdown: {
                                overlay: (
                                    <>
                                        <LemonButton disabledReason="Coming soon" fullWidth>
                                            Import from Bit.ly
                                        </LemonButton>
                                        <LemonButton disabledReason="Coming soon" fullWidth>
                                            Import from Dub.co
                                        </LemonButton>
                                        <LemonButton disabledReason="Coming soon" fullWidth>
                                            Import from CSV
                                        </LemonButton>
                                    </>
                                ),
                                placement: 'bottom-end',
                            },
                        }}
                    >
                        Create link
                    </LemonButton>
                }
            />

            <LemonBanner type="warning">
                <p>
                    Links are currently in an experimental state. For many cases this will work just fine but for others
                    there may be unexpected issues and we do not offer official customer support for it in these cases.
                </p>
            </LemonBanner>

            <ProductIntroduction
                isEmpty={shouldShowEmptyState}
                productName="Links"
                productKey={ProductKey.LINKS}
                thingName="link"
                description="Start creating links for your marketing campaigns, referral programs, and more."
                action={() => router.actions.push(urls.link('new'))}
                docsURL="https://posthog.com/docs/links"
                className="my-0"
            />

            {!shouldShowEmptyState && <LemonTable loading={linksLoading} columns={columns} dataSource={links} />}
        </SceneContent>
    )
}
