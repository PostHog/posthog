import { PostHog } from 'posthog-node'

let _client: PostHog | undefined

export const getPostHogClient = () => {
    if (!_client) {
        _client = new PostHog('sTMFPsFhdP1Ssg', {
            host: 'https://us.i.posthog.com',
            flushAt: 1,
            flushInterval: 0,
        })
    }

    return _client
}
