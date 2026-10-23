import { router } from 'kea-router'

import { IconPlus } from '@posthog/icons'
import {
    Button,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuGroup,
    DropdownMenuItem,
    DropdownMenuLabel,
    DropdownMenuTrigger,
} from '@posthog/quill'

import { urls } from 'scenes/urls'

import { LegalDocumentType } from './legalDocumentsLogic'

interface NewLegalDocumentOption {
    title: string
    description: string
    url?: string
    disabledReason?: string
    dataAttr: string
}

export function QuillNewLegalDocumentMenu({
    existingDocumentTypes,
    baaBlockedReason,
}: {
    existingDocumentTypes: Set<LegalDocumentType>
    baaBlockedReason?: string
}): JSX.Element {
    const alreadyExistsReason = (type: LegalDocumentType): string | undefined =>
        existingDocumentTypes.has(type)
            ? `Your organization already has a ${type}. Contact support if you need a new one.`
            : undefined
    const options: NewLegalDocumentOption[] = [
        {
            title: 'Data Processing Agreement (DPA)',
            description: 'GDPR-compliant DPA for any paid or free customer.',
            url: urls.legalDocumentNew('DPA'),
            disabledReason: alreadyExistsReason('DPA'),
            dataAttr: 'new-legal-document-menu-dpa',
        },
        {
            title: 'Business Associate Agreement (BAA)',
            description: 'HIPAA BAA — requires a Boost, Scale, or Enterprise add-on.',
            url: urls.legalDocumentNew('BAA'),
            disabledReason: alreadyExistsReason('BAA') ?? baaBlockedReason,
            dataAttr: 'new-legal-document-menu-baa',
        },
        {
            title: 'Master Service Agreement (MSA)',
            description: 'Negotiated with sales — contact your TAM or PostHog support to sign one.',
            disabledReason: 'MSAs are negotiated by sales. Contact your TAM or PostHog support to sign an MSA.',
            dataAttr: 'new-legal-document-menu-msa',
        },
    ]

    return (
        <DropdownMenu>
            <DropdownMenuTrigger
                render={
                    <Button
                        variant="primary"
                        data-attr="new-legal-document-button"
                        tooltip="Generate a new legal document"
                    />
                }
            >
                <IconPlus />
                New
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
                <DropdownMenuGroup>
                    <DropdownMenuLabel>Document types</DropdownMenuLabel>
                    {options.map((option) => (
                        <DropdownMenuItem
                            key={option.dataAttr}
                            disabledReason={option.disabledReason}
                            onClick={() => option.url && router.actions.push(option.url)}
                            data-attr={option.dataAttr}
                            description={option.description}
                        >
                            {option.title}
                        </DropdownMenuItem>
                    ))}
                </DropdownMenuGroup>
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
