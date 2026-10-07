import type { EmailTemplate } from 'scenes/hog-functions/email-templater/types'

import { NEW_TEMPLATE } from './constants'
import type { MessageTemplate } from './types'

export interface BrandedStarterInput {
    name: string
    primaryColor: string
    logoUrl?: string
}

type Design = NonNullable<EmailTemplate['design']>
type Row = Design['body']['rows'][number]
type Column = Row['columns'][number]
type Content = Column['contents'][number]

const TEXT_COLOR = '#222222'
const FOOTER_TEXT_COLOR = '#6b6b6b'

export function brandDisplayName(name: string): string {
    return name.replace(/[{}]/g, '').trim()
}

function escapeHtml(text: string): string {
    return text.replace(/[&<>"']/g, (character) => {
        return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[character]!
    })
}

function buttonTextColor(color: string): string {
    const channels = [1, 3, 5].map((index) => {
        const value = parseInt(color.slice(index, index + 2), 16) / 255
        return value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4
    })
    const luminance = 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]
    return 1.05 / (luminance + 0.05) >= (luminance + 0.05) / 0.05 ? '#ffffff' : '#000000'
}

function block(id: string, type: Content['type'], values: Content['values']): Content {
    return {
        id: `branded-starter-${id}`,
        type,
        values: {
            _meta: { htmlID: id, htmlClassNames: id },
            selectable: true,
            draggable: true,
            duplicatable: true,
            deletable: true,
            hideable: true,
            containerPadding: '16px 24px',
            ...values,
        },
    }
}

function logoBlock(logoUrl: string, brandName: string): Content {
    return block('u_content_image_1', 'image', {
        src: { url: logoUrl, autoWidth: false, maxWidth: '29%' },
        altText: brandName,
        textAlign: 'center',
    })
}

function brandNameHeadingBlock(escapedBrandName: string): Content {
    return block('u_content_heading_2', 'heading', {
        text: escapedBrandName,
        headingType: 'h2',
        fontSize: '24px',
        textAlign: 'center',
        color: TEXT_COLOR,
    })
}

function greetingBlock(): Content {
    return block('u_content_heading_1', 'heading', {
        text: 'Hi there,',
        headingType: 'h1',
        fontSize: '28px',
        color: TEXT_COLOR,
    })
}

function messagePlaceholderBlock(): Content {
    return block('u_content_text_1', 'text', {
        text: '<p>Write your message here.</p>',
        fontSize: '16px',
        color: TEXT_COLOR,
        lineHeight: '150%',
    })
}

function callToActionBlock(primaryColor: string): Content {
    const textColor = buttonTextColor(primaryColor)
    return block('u_content_button_1', 'button', {
        text: '<span>Get started</span>',
        href: { name: 'web', values: { href: 'https://example.com', target: '_blank' } },
        buttonColors: {
            color: textColor,
            backgroundColor: primaryColor,
            hoverColor: textColor,
            hoverBackgroundColor: primaryColor,
        },
        size: { autoWidth: true, width: '100%' },
        fontSize: '16px',
        padding: '12px 24px',
        borderRadius: '6px',
    })
}

function unsubscribeFooterBlock(escapedBrandName: string): Content {
    return {
        ...block('u_content_custom_unsubscribe_link_1', 'custom', {
            unsubscribe_link_content: `<p style="text-align: center; font-size: 12px; color: ${FOOTER_TEXT_COLOR};">You get this email because you use ${escapedBrandName}. <a href="{{ unsubscribe_url }}" style="color: ${FOOTER_TEXT_COLOR}; text-decoration: underline;">Unsubscribe</a></p>`,
        }),
        slug: 'unsubscribe_link',
    }
}

function accentTopBorder(primaryColor: string): Column['values']['border'] {
    return { borderTopWidth: '4px', borderTopStyle: 'solid', borderTopColor: primaryColor }
}

function singleColumnRow(index: number, contents: Content[], border: Column['values']['border'] = {}): Row {
    return {
        id: `branded-starter-row-${index}`,
        cells: [1],
        columns: [{ id: `branded-starter-column-${index}`, contents, values: { padding: '0px', border } }],
        values: { backgroundColor: '#ffffff', padding: '0px' },
    }
}

function contentCounters(hasLogo: boolean): Design['counters'] {
    return {
        u_row: 3,
        u_column: 3,
        u_content_heading: hasLogo ? 1 : 2,
        u_content_image: hasLogo ? 1 : 0,
        u_content_text: 1,
        u_content_button: 1,
        u_content_custom_unsubscribe_link: 1,
    }
}

function brandedDesign({ name, primaryColor, logoUrl }: BrandedStarterInput): Design {
    const brandName = brandDisplayName(name)
    const escapedBrandName = escapeHtml(brandName)
    const header = logoUrl ? logoBlock(logoUrl, brandName) : brandNameHeadingBlock(escapedBrandName)
    return {
        schemaVersion: 16,
        counters: contentCounters(!!logoUrl),
        body: {
            id: 'branded-starter-body',
            headers: [],
            footers: [],
            rows: [
                singleColumnRow(0, [header], accentTopBorder(primaryColor)),
                singleColumnRow(1, [greetingBlock(), messagePlaceholderBlock(), callToActionBlock(primaryColor)]),
                singleColumnRow(2, [unsubscribeFooterBlock(escapedBrandName)]),
            ],
            values: {
                backgroundColor: '#f5f5f5',
                contentWidth: '600px',
                contentAlign: 'center',
                fontFamily: { label: 'Arial', value: 'arial,helvetica,sans-serif' },
                textColor: TEXT_COLOR,
                linkStyle: { body: true, linkColor: TEXT_COLOR, linkUnderline: true },
            },
        },
    }
}

export function buildBrandedStarter(input: BrandedStarterInput): MessageTemplate {
    const brandName = brandDisplayName(input.name)
    return {
        ...NEW_TEMPLATE,
        name: `${brandName} starter template`,
        description: 'A branded starting point for your email.',
        content: {
            templating: 'liquid',
            email: {
                from: '',
                to: '',
                subject: `Hello from ${brandName}`,
                html: '',
                text: '',
                design: brandedDesign(input),
            },
        },
    }
}
