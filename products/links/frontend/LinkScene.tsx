import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { router } from 'kea-router'
import { QRCodeSVG } from 'qrcode.react'

import { IconCopy, IconDownload } from '@posthog/icons'
import {
    LemonButton,
    LemonDivider,
    LemonInput,
    LemonLabel,
    LemonSelect,
    LemonSelectOptions,
    LemonSkeleton,
    LemonTag,
    LemonTextArea,
    Link,
} from '@posthog/lemon-ui'

import { NotFound } from 'lib/components/NotFound'
import { useFileSystemLogView } from 'lib/hooks/useFileSystemLogView'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneDivider } from '~/layout/scenes/components/SceneDivider'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { AVAILABLE_DOMAINS, AvailableDomain, LinkLogicProps, linkLogic } from './linkLogic'

export const scene: SceneExport<LinkLogicProps> = {
    component: LinkScene,
    logic: linkLogic,
    paramsToProps: ({ params: { id } }) => ({ id: id && id !== 'new' ? id : 'new' }),
}

const SOON_TAG = (
    <LemonTag type="completion" size="small" className="ml-2">
        SOON
    </LemonTag>
)

const PAID_TAG = (
    <LemonTag type="success" size="small" className="ml-2">
        PAID
    </LemonTag>
)

const DomainLabelWithTag = ({
    domain,
    soon,
    paid,
}: {
    domain: string
    soon?: boolean
    paid?: boolean
}): JSX.Element => {
    return (
        <div>
            <span>{domain}</span>
            {soon && SOON_TAG}
            {paid && PAID_TAG}
        </div>
    )
}

const DOMAIN_OPTIONS: LemonSelectOptions<AvailableDomain> = AVAILABLE_DOMAINS.map((domain) => ({
    label: <DomainLabelWithTag domain={domain.label} soon={domain.soon} paid={domain.paid} />,
    value: domain.value,
    disabledReason: domain.soon ? 'Coming soon...' : undefined,
}))

export function LinkScene({ id }: LinkLogicProps): JSX.Element {
    const { link, linkLoading, isLinkSubmitting, isEditingLink, linkMissing } = useValues(linkLogic)
    const { submitLinkRequest, loadLink, editLink, deleteLink } = useActions(linkLogic)

    const linkId = link?.id && link?.id !== 'new' ? link.id : null

    useFileSystemLogView({
        type: 'link',
        ref: linkId,
        enabled: Boolean(linkId && !linkLoading),
        deps: [linkId, linkLoading],
    })

    if (linkMissing) {
        return <NotFound object="link" />
    }

    if (linkLoading) {
        return <LemonSkeleton active />
    }

    const isNewLink = id === 'new' || id === undefined
    const displayForm = isEditingLink || isNewLink
    const fullLink = `https://${link.short_link_domain}/${link.short_code}`

    return (
        <Form id="link" formKey="link" logic={linkLogic}>
            <SceneContent>
                <SceneTitleSection
                    name={fullLink}
                    description={null}
                    resourceType={{
                        type: 'link',
                    }}
                    actions={
                        <>
                            {!linkLoading ? (
                                displayForm ? (
                                    <>
                                        <LemonButton
                                            type="secondary"
                                            data-attr="cancel-link"
                                            onClick={() => {
                                                if (isEditingLink) {
                                                    editLink(false)
                                                    loadLink()
                                                } else {
                                                    router.actions.push(urls.links())
                                                }
                                            }}
                                            size="small"
                                            disabledReason={isLinkSubmitting ? 'Saving…' : undefined}
                                        >
                                            Cancel
                                        </LemonButton>
                                        <LemonButton
                                            type="primary"
                                            htmlType="submit"
                                            data-attr="save-link"
                                            onClick={() => {
                                                submitLinkRequest(link)
                                            }}
                                            loading={isLinkSubmitting}
                                            form="link"
                                            size="small"
                                        >
                                            Save
                                        </LemonButton>
                                    </>
                                ) : (
                                    <>
                                        <LemonButton
                                            data-attr="delete-link"
                                            status="danger"
                                            type="secondary"
                                            size="small"
                                            onClick={() => {
                                                LemonDialog.open({
                                                    title: 'Permanently delete link?',
                                                    description:
                                                        'Doing so will remove the link and the existing redirect rules. You will NOT lose access to the `$clicklink` events.',
                                                    primaryButton: {
                                                        children: 'Delete',
                                                        type: 'primary',
                                                        status: 'danger',
                                                        'data-attr': 'confirm-delete-link',
                                                        onClick: () => {
                                                            // conditional above ensures link is not NewLink
                                                            deleteLink(link?.id)
                                                        },
                                                    },
                                                    secondaryButton: {
                                                        children: 'Close',
                                                        type: 'secondary',
                                                    },
                                                })
                                            }}
                                        >
                                            Delete
                                        </LemonButton>
                                        <LemonButton
                                            type="secondary"
                                            onClick={() => editLink(true)}
                                            loading={false}
                                            data-attr="edit-link"
                                            size="small"
                                        >
                                            Edit
                                        </LemonButton>
                                    </>
                                )
                            ) : undefined}
                        </>
                    }
                />

                <SceneDivider />

                <div className="space-y-4">
                    <div className="flex gap-8">
                        <div className="flex-1 space-y-4">
                            <div className="flex flex-col">
                                <LemonLabel>Destination URL</LemonLabel>
                                {displayForm ? (
                                    <div className="flex gap-1 items-center">
                                        <LemonField name="redirect_url">
                                            <LemonInput
                                                placeholder="https://loooooooooooooong.posthog.com/"
                                                fullWidth
                                                autoWidth={false}
                                            />
                                        </LemonField>
                                    </div>
                                ) : (
                                    <Link to={link.redirect_url} className="text-muted" target="_blank">
                                        {link.redirect_url}
                                    </Link>
                                )}
                            </div>

                            <div className="flex flex-col">
                                <LemonLabel>Short Link</LemonLabel>
                                {displayForm ? (
                                    <div className="flex gap-1 items-center">
                                        <LemonField name="short_link_domain">
                                            <LemonSelect<AvailableDomain>
                                                options={DOMAIN_OPTIONS}
                                                className="text-muted"
                                            />
                                        </LemonField>
                                        <span className="text-muted">/</span>
                                        <LemonField name="short_code" className="w-full">
                                            <LemonInput
                                                fullWidth
                                                placeholder="short"
                                                className="flex-1"
                                                autoWidth={false}
                                            />
                                        </LemonField>
                                    </div>
                                ) : (
                                    <Link to={fullLink} target="_blank">
                                        {fullLink}
                                    </Link>
                                )}
                            </div>

                            <div className="flex flex-col">
                                <LemonLabel>Description (optional)</LemonLabel>
                                {displayForm ? (
                                    <div className="flex gap-1 items-center">
                                        <LemonField name="description">
                                            <LemonTextArea
                                                placeholder="Add a description so that you can easily identify this link"
                                                minRows={2}
                                            />
                                        </LemonField>
                                    </div>
                                ) : (
                                    <div>{link.description || <span className="text-muted">No description</span>}</div>
                                )}
                            </div>
                        </div>

                        <LemonDivider vertical />

                        <div className="flex-1 space-y-6 max-w-80">
                            <div>
                                <div className="flex justify-between items-center">
                                    <LemonLabel>
                                        <span className="flex items-center gap-1">QR Code</span>
                                    </LemonLabel>
                                    <div className="flex flex-row">
                                        <LemonButton
                                            icon={<IconDownload />}
                                            size="xsmall"
                                            onClick={() => {}}
                                            tooltip="Download QR code"
                                        />
                                        <LemonButton
                                            icon={<IconCopy />}
                                            size="xsmall"
                                            onClick={() => {}}
                                            tooltip="Copy to clipboard"
                                        />
                                    </div>
                                </div>

                                <div className="border rounded-md p-4 mt-2 bg-bg-light flex items-center justify-center">
                                    <div className="text-center">
                                        <QRCodeSVG
                                            size={128}
                                            value={fullLink}
                                            level="H"
                                            imageSettings={{
                                                src: '/static/posthog-icon.svg',
                                                height: 35,
                                                width: 35,
                                                excavate: true,
                                            }}
                                        />
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            </SceneContent>
        </Form>
    )
}
