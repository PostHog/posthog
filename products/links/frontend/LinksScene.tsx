import { IconPlus } from '@posthog/icons'
import { LemonButton, LemonTable, LemonTableColumn, Link } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { router } from 'kea-router'
import { PageHeader } from 'lib/components/PageHeader'
import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonMenuOverlay } from 'lib/lemon-ui/LemonMenu/LemonMenu'
import { createdAtColumn, createdByColumn } from 'lib/lemon-ui/LemonTable/columnUtils'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import stringWithWBR from 'lib/utils/stringWithWBR'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { LinkType, ProductKey } from '~/types'

import { LinkMetricSparkline } from './LinkMetricSparkline'
import { linksLogic } from './linksLogic'

export const scene: SceneExport = {
    component: LinksScene,
    logic: linksLogic,
}

export function LinksScene(): JSX.Element {
    const { links, linksLoading } = useValues(linksLogic)
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
                    // TODO: Update URL to link to page with all `$linkclick` events
                    // for this specific link
                    <Link to="/insights">
                        <LinkMetricSparkline id={link.id} />
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
                                        disabledReason: 'Coming soon',
                                        onClick: () => {},
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
        <>
            <PageHeader
                buttons={
                    <LemonButton
                        type="primary"
                        icon={<IconPlus />}
                        onClick={() => router.actions.push(urls.link('new'))}
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
                delimited
            />

            <ProductIntroduction
                isEmpty={shouldShowEmptyState}
                productName="Links"
                productKey={ProductKey.LINKS}
                thingName="link"
                description="Start creating links for your marketing campaigns, referral programs, and more."
                action={() => router.actions.push(urls.link('new'))}
                docsURL="https://posthog.com/docs/links"
            />

            {!shouldShowEmptyState && <LemonTable loading={linksLoading} columns={columns} dataSource={links} />}
        </>
    )
}
