import type { EmailTemplate } from 'scenes/hog-functions/email-templater/types'

import type { CyclotronJobInputType, HogFunctionMappingType, UserBasicType } from '~/types'

export interface FunctionTemplateContent {
    template_id: string
    inputs: Record<string, CyclotronJobInputType>
    mappings?: HogFunctionMappingType[]
}

export interface MessageTemplate {
    id: string
    name: string
    description: string
    type: 'email' | 'function'
    content: {
        templating: 'liquid' | 'hog'
        email?: EmailTemplate
        function?: FunctionTemplateContent
    }
    created_at: string | null
    updated_at: string | null
    created_by: UserBasicType | null
}
