import { isIdJagAccessToken } from './id-jag'
import { isProjectSecretKey } from './project-secret-key'

export type McpAuthMethod = 'oauth' | 'personal_api_key' | 'project_secret_key' | 'id_jag' | 'none' | 'unknown'

export function classifyAuthMethod(token: string | undefined): McpAuthMethod {
    if (!token) {
        return 'none'
    }
    if (token.startsWith('pha_')) {
        return 'oauth'
    }
    if (token.startsWith('phx_')) {
        return 'personal_api_key'
    }
    if (isProjectSecretKey(token)) {
        return 'project_secret_key'
    }
    if (isIdJagAccessToken(token)) {
        return 'id_jag'
    }
    return 'unknown'
}
