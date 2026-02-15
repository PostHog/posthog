import { ErrorCode } from '@/lib/errors'

const AUTH_ERROR_CODES = [ErrorCode.INACTIVE_OAUTH_TOKEN, ErrorCode.INVALID_API_KEY]

/**
 * Converts known auth failures from MCP internals into 401 responses.
 */
export const mapAuthErrorResponse = async (response: Response): Promise<Response> => {
    if (response.ok) {
        return response
    }

    const body = await response.clone().text()
    const isAuthError = AUTH_ERROR_CODES.some((errorCode) => body.includes(errorCode))

    if (isAuthError) {
        return new Response('OAuth token is inactive', { status: 401 })
    }

    return response
}
