export class PostHogClient {
    private baseUrl: string
    private accessToken: string
    private refreshToken: string

    constructor(baseUrl: string, accessToken: string, refreshToken: string) {
        this.baseUrl = baseUrl
        this.accessToken = accessToken
        this.refreshToken = refreshToken
    }

    async refreshAccessToken(): Promise<void> {
        const response = await fetch(`${this.baseUrl}/oauth/token/`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
            body: new URLSearchParams({
                grant_type: 'refresh_token',
                refresh_token: this.refreshToken,
            }),
        })

        if (!response.ok) {
            const text = await response.text()
            throw new Error(`Token refresh failed: ${response.status} ${text}`)
        }

        const tokenData = await response.json()
        this.accessToken = tokenData.access_token
        if (tokenData.refresh_token) {
            this.refreshToken = tokenData.refresh_token
        }
    }

    async request(path: string, options?: RequestInit): Promise<Response> {
        const url = `${this.baseUrl}${path}`
        const headers = {
            Authorization: `Bearer ${this.accessToken}`,
            ...options?.headers,
        }

        let response = await fetch(url, { ...options, headers })

        if (response.status === 401) {
            await this.refreshAccessToken()
            headers.Authorization = `Bearer ${this.accessToken}`
            response = await fetch(url, { ...options, headers })
        }

        return response
    }
}
