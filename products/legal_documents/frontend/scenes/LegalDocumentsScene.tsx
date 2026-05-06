import { useValues } from 'kea'

import { IconBalance, IconDownload, IconPlusSmall } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonTable, LemonTag, Link } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonMenu, LemonMenuItems } from 'lib/lemon-ui/LemonMenu'
import { organizationLogic } from 'scenes/organizationLogic'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { sceneConfigurations } from 'scenes/scenes'
import { Scene, SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { getLegalDocumentsDownloadRetrieveUrl } from '../generated/api'
import { LegalDocument, LegalDocumentType, legalDocumentsLogic } from './legalDocumentsLogic'

function buildNewMenuItems(existingTypes: Set<LegalDocumentType>): LemonMenuItems {
    const alreadyExistsReason = (type: LegalDocumentType): string | undefined =>
        existingTypes.has(type)
            ? `Your organization already has a ${type}. Contact support if you need a new one.`
            : undefined
    return [
        {
            title: 'Document types',
            items: [
                {
                    label: (
                        <div className="flex flex-col text-sm py-1">
                            <strong>Data Processing Agreement (DPA)</strong>
                            <span className="text-xs font-normal text-muted">
                                GDPR-compliant DPA for any paid or free customer.
                            </span>
                        </div>
                    ),
                    to: urls.legalDocumentNew('DPA'),
                    disabledReason: alreadyExistsReason('DPA'),
                    'data-attr': 'new-legal-document-menu-dpa',
                },
                {
                    label: (
                        <div className="flex flex-col text-sm py-1">
                            <strong>Business Associate Agreement (BAA)</strong>
                            <span className="text-xs font-normal text-muted">
                                HIPAA BAA — requires a Boost, Scale, or Enterprise add-on.
                            </span>
                        </div>
                    ),
                    to: urls.legalDocumentNew('BAA'),
                    disabledReason: alreadyExistsReason('BAA'),
                    'data-attr': 'new-legal-document-menu-baa',
                },
            ],
        },
    ]
}

export const scene: SceneExport = {
    component: LegalDocumentsScene,
    logic: legalDocumentsLogic,
}

export function LegalDocumentsScene(): JSX.Element {
    const { legalDocuments, legalDocumentsLoading, existingDocumentTypes } = useValues(legalDocumentsLogic)
    const { isAdminOrOwner, currentOrganizationId } = useValues(organizationLogic)
    const { isCloudOrDev } = useValues(preflightLogic)
    const isEnabled = useFeatureFlag('LEGAL_DOCUMENTS')

    if (!isCloudOrDev) {
        return (
            <SceneContent>
                <SceneTitleSection
                    name={sceneConfigurations[Scene.LegalDocuments].name}
                    resourceType={{ type: 'default_icon_type', forceIcon: <IconBalance /> }}
                />
                <LemonBanner type="info">
                    <p className="mb-0">Legal documents are only available on PostHog Cloud.</p>
                </LemonBanner>
            </SceneContent>
        )
    }

    if (!isEnabled) {
        return (
            <SceneContent>
                <SceneTitleSection
                    name={sceneConfigurations[Scene.LegalDocuments].name}
                    resourceType={{ type: 'default_icon_type', forceIcon: <IconBalance /> }}
                />
                <LemonBanner type="info">
                    <p className="mb-0">Legal documents aren't available for your organization yet.</p>
                </LemonBanner>
            </SceneContent>
        )
    }

    if (isAdminOrOwner === false) {
        return (
            <SceneContent>
                <SceneTitleSection
                    name={sceneConfigurations[Scene.LegalDocuments].name}
                    description={sceneConfigurations[Scene.LegalDocuments].description}
                    resourceType={{ type: 'default_icon_type', forceIcon: <IconBalance /> }}
                />
                <LemonBanner type="warning">
                    <h2 className="mb-2">Admin access required</h2>
                    <p className="mb-0">
                        Only organization admins and owners can generate or review legal documents. Ask one of them to
                        sign in if you need a BAA or DPA.
                    </p>
                </LemonBanner>
            </SceneContent>
        )
    }

    return (
        <SceneContent>
            <SceneTitleSection
                name={sceneConfigurations[Scene.LegalDocuments].name}
                description={sceneConfigurations[Scene.LegalDocuments].description}
                resourceType={{ type: 'default_icon_type', forceIcon: <IconBalance /> }}
                actions={
                    <LemonMenu items={buildNewMenuItems(existingDocumentTypes)} placement="bottom-end">
                        <LemonButton
                            type="primary"
                            icon={<IconPlusSmall />}
                            size="small"
                            data-attr="new-legal-document-button"
                            tooltip="Generate a new legal document"
                        >
                            New
                        </LemonButton>
                    </LemonMenu>
                }
            />

            <LemonTable
                dataSource={legalDocuments}
                loading={legalDocumentsLoading}
                emptyState="You haven't generated any legal documents yet. Click New to create one."
                columns={[
                    {
                        title: 'Type',
                        dataIndex: 'document_type',
                        width: 80,
                        render: (_: any, row: LegalDocument) => (
                            <span className="font-semibold">{row.document_type}</span>
                        ),
                    },
                    {
                        title: 'Company',
                        render: (_: any, row: LegalDocument) => row.company_name,
                    },
                    {
                        title: 'Signer',
                        render: (_: any, row: LegalDocument) => row.representative_email,
                    },
                    {
                        title: 'Status',
                        width: 150,
                        render: (_: any, row: LegalDocument) =>
                            row.status === 'signed' ? (
                                <LemonTag type="success">Signed</LemonTag>
                            ) : (
                                <LemonTag type="warning">Awaiting signature</LemonTag>
                            ),
                    },
                    {
                        title: 'Signed copy',
                        width: 140,
                        render: (_: any, row: LegalDocument) =>
                            row.status === 'signed' && currentOrganizationId ? (
                                <Link
                                    to={getLegalDocumentsDownloadRetrieveUrl(currentOrganizationId, row.id)}
                                    target="_blank"
                                >
                                    <span className="inline-flex items-center gap-1">
                                        <IconDownload />
                                        Download
                                    </span>
                                </Link>
                            ) : (
                                <span className="text-muted">—</span>
                            ),
                    },
                    {
                        title: 'Submitted',
                        width: 180,
                        render: (_: any, row: LegalDocument) => <TZLabel time={row.created_at} />,
                    },
                    {
                        title: 'By',
                        render: (_: any, row: LegalDocument) =>
                            row.created_by?.first_name || row.created_by?.email || '—',
                    },
                ]}
            />
        </SceneContent>
    )
}

export default LegalDocumentsScene
