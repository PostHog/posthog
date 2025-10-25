export interface InkeepResponse {
    choices: Array<{
        message: {
            content: string
        }
    }>
}

export async function docsSearch(apiKey: string, userQuery: string): Promise<string> {
    if (!apiKey) {
        throw new Error('No API key provided')
    }

    const response = await fetch('https://api.inkeep.com/v1/chat/completions', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            Authorization: `Bearer ${apiKey}`,
        },
        body: JSON.stringify({
            model: 'inkeep-context-gpt-4o',
            messages: [{ role: 'user', content: userQuery }],
        }),
    })

    if (!response.ok) {
        const errorText = await response.text()
        console.error('Inkeep API error:', errorText)
        throw new Error(`Error querying Inkeep API: ${response.status} ${errorText}`)
    }

    const data = (await response.json()) as InkeepResponse

    if (
        data.choices &&
        data.choices.length > 0 &&
        data.choices[0]?.message &&
        data.choices[0].message.content
    ) {
        return data.choices[0].message.content
    }
    console.error('Inkeep API response format unexpected:', data)
    throw new Error('Unexpected response format from Inkeep API.')
}
