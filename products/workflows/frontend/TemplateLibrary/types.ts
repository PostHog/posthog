import type { EmailTemplate } from 'scenes/hog-functions/email-templater/types'

import type { UserBasicType } from '~/types'

import type { MessageTemplateApi } from 'products/messaging/frontend/generated/api.schemas'

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
    transactional_hog_flow_id?: MessageTemplateApi['transactional_hog_flow_id']
    draft_content?: MessageTemplateApi['draft_content']
    sensitive?: MessageTemplateApi['sensitive']
    tags?: MessageTemplateApi['tags']
}
