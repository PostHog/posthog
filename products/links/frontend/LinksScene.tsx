import { router } from 'kea-router'

import { LemonBanner, LemonButton, Link } from '@posthog/lemon-ui'

import api from 'lib/api'
import { defineEntityListScene } from 'lib/components/EntityList'
import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { LemonMenuOverlay } from 'lib/lemon-ui/LemonMenu/LemonMenu'
import { createdAtColumn, createdByColumn } from 'lib/lemon-ui/LemonTable/columnUtils'
import stringWithWBR from 'lib/utils/stringWithWBR'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { ProductKey } from '~/queries/schema/schema-general'
import { LinkType } from '~/types'

import { LinkMetricSparkline } from './LinkMetricSparkline'

export const scene = defineEntityListScene<LinkType>({
    type: 'link',
    scene: Scene.Links,
    url: urls.links(),
    productKey: ProductKey.LINKS,
    mode: 'client',
    load: async () => ({ results: (await api.links.list()).results }),
    nameColumn: {
        title: 'Key',
        width: '40%',
        render: (link) => <span>{stringWithWBR(`${link.short_link_domain}/${link.short_code}`, 17)}</span>,
        description: (link) => link.redirect_url,
    },
    columns: [
        createdByColumn<LinkType>(),
        createdAtColumn<LinkType>(),
        {
            title: 'Last 7 days',
            render: function RenderLinkMetricSparkline(_, link) {
                // TODO: Update URL to link to page with all `$linkclick` events for this specific link
                return (
                    <Link to="/insights">
                        <LinkMetricSparkline id={link.id} />
                    </Link>
                )
            },
        },
    ],
    rowMenu: (link) => (
        <LemonMenuOverlay
            items={[
                { label: 'Edit link', onClick: () => router.actions.push(urls.link(link.id)) },
                { label: 'Delete link', status: 'danger', disabledReason: 'Coming soon', onClick: () => {} },
            ]}
        />
    ),
    newButton: {
        label: 'Create link',
        to: urls.link('new'),
        shortcutName: 'NewLink',
        sideAction: {
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
        },
    },
    hideTableWhenEmpty: true,
    banner: ({ isEmpty }) => (
        <>
            <LemonBanner type="error">
                <h2>Links are extremely WIP</h2>
                <p>
                    Links were started on the Tulum 2025 hackathon, and are not currently in use. The UI and Django
                    backend are fully functional, but there's no backend to actually track/redirect clicks. This should
                    be implemented in the future, probably part of our NodeJS infrastructure - we've initially built it
                    in Rust.
                </p>
            </LemonBanner>
            <ProductIntroduction
                isEmpty={isEmpty}
                productName="Links"
                productKey={ProductKey.LINKS}
                thingName="link"
                description="Start creating links for your marketing campaigns, referral programs, and more."
                action={() => router.actions.push(urls.link('new'))}
                docsURL="https://posthog.com/docs/links"
                className="my-0"
            />
        </>
    ),
})
