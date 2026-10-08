import type { EmailTemplate } from 'scenes/hog-functions/email-templater/types'

import type { UserBasicType } from '~/types'

import type { MessageTemplateApi as MessageTemplateListApi } from 'products/messaging/frontend/generated/api.schemas'

export interface MessageTemplate {
    id: string
    name: string
    description: string
    content: {
        templating: 'liquid' | 'hog'
        email: EmailTemplate
    }
    created_at: string | null
    updated_at: string | null
    created_by: UserBasicType | null
}

export type MessageTemplateListItem = MessageTemplate | MessageTemplateListApi
