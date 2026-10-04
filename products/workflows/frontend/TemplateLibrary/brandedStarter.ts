import type { EmailTemplate } from 'scenes/hog-functions/email-templater/types'

import { NEW_TEMPLATE } from './constants'
import type { MessageTemplate } from './types'

export interface BrandedStarterInput {
    name: string
    primaryColor: string
    logoUrl?: string
}

type Design = NonNullable<EmailTemplate['design']>
type Content = Design['body']['rows'][number]['columns'][number]['contents'][number]

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

export function buildBrandedStarter({ name, primaryColor, logoUrl }: BrandedStarterInput): MessageTemplate {
    const safeName = name.trim().replace(/[{}]/g, '')
    const escapedName = safeName.replace(/[&<>"']/g, (character) => {
        return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[character]!
    })
    const textColor = buttonTextColor(primaryColor)
    const header = logoUrl
        ? block('u_content_image_1', 'image', {
              src: { url: logoUrl, autoWidth: false, maxWidth: '29%' },
              altText: safeName,
              textAlign: 'center',
          })
        : block('u_content_heading_2', 'heading', {
              text: escapedName,
              headingType: 'h2',
              fontSize: '24px',
              textAlign: 'center',
              color: '#222222',
          })
    const rows = [
        [header],
        [
            block('u_content_heading_1', 'heading', {
                text: "Hi {{ person.properties.first_name | default: 'there' }}",
                headingType: 'h1',
                fontSize: '28px',
                color: '#222222',
            }),
            block('u_content_text_1', 'text', {
                text: '<p>Write your message here.</p>',
                fontSize: '16px',
                color: '#222222',
                lineHeight: '150%',
            }),
            block('u_content_button_1', 'button', {
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
            }),
        ],
        [
            {
                ...block('u_content_custom_unsubscribe_link_1', 'custom', {
                    unsubscribe_link_content: `<p style="text-align: center; font-size: 12px; color: #6b6b6b;">You get this email because you use ${escapedName}. <a href="{{ unsubscribe_url }}" style="color: #6b6b6b; text-decoration: underline;">Unsubscribe</a></p>`,
                }),
                slug: 'unsubscribe_link',
            },
        ],
    ]
    return {
        ...NEW_TEMPLATE,
        name: `${safeName} starter template`,
        description: 'A branded starting point for your email.',
        content: {
            templating: 'liquid',
            email: {
                from: '',
                to: '',
                subject: `Hello from ${safeName}`,
                html: '',
                text: '',
                design: {
                    schemaVersion: 16,
                    counters: {
                        u_row: 3,
                        u_column: 3,
                        u_content_heading: logoUrl ? 1 : 2,
                        u_content_image: logoUrl ? 1 : 0,
                        u_content_text: 1,
                        u_content_button: 1,
                        u_content_custom_unsubscribe_link: 1,
                    },
                    body: {
                        id: 'branded-starter-body',
                        headers: [],
                        footers: [],
                        rows: rows.map((contents, index) => ({
                            id: `branded-starter-row-${index}`,
                            cells: [1],
                            columns: [
                                {
                                    id: `branded-starter-column-${index}`,
                                    contents,
                                    values: {
                                        padding: '0px',
                                        border:
                                            index === 0
                                                ? {
                                                      borderTopWidth: '4px',
                                                      borderTopStyle: 'solid',
                                                      borderTopColor: primaryColor,
                                                  }
                                                : {},
                                    },
                                },
                            ],
                            values: { backgroundColor: '#ffffff', padding: '0px' },
                        })),
                        values: {
                            backgroundColor: '#f5f5f5',
                            contentWidth: '600px',
                            contentAlign: 'center',
                            fontFamily: { label: 'Arial', value: 'arial,helvetica,sans-serif' },
                            textColor: '#222222',
                            linkStyle: { body: true, linkColor: '#222222', linkUnderline: true },
                        },
                    },
                },
            },
        },
    }
}
