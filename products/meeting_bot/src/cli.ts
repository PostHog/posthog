async function main(): Promise<void> {
    const [meetingUrl] = process.argv.slice(2)
    const port = process.env.PORT || '3030'

    if (!meetingUrl) {
        console.error('usage: pnpm join <meeting-url>')
        process.exit(1)
    }

    // Goes through the running server rather than calling Recall directly, so the bot is dispatched with
    // the same shared secret the server is currently accepting.
    const response = await fetch(`http://localhost:${port}/bots`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ meeting_url: meetingUrl }),
    })

    const body = await response.text()
    if (!response.ok) {
        console.error(`failed (${response.status}): ${body}`)
        process.exit(1)
    }
    console.info(body)
}

void main()
