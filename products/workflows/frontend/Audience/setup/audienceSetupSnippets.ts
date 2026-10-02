export interface AudienceSetupSnippetContext {
    projectToken: string
    host: string
    topicKeys: string[]
}

const BARE_OBJECT_KEY = /^[A-Za-z_$][\w$]*$/

function singleQuoted(text: string): string {
    return `'${text.replace(/\\/g, '\\\\').replace(/'/g, "\\'")}'`
}

function objectKey(topicKey: string): string {
    return BARE_OBJECT_KEY.test(topicKey) ? topicKey : singleQuoted(topicKey)
}

const EXAMPLE_UNSUBSCRIBED_TOPIC_INDEX = 0

function exampleSubscribed(topicIndex: number): boolean {
    return topicIndex !== EXAMPLE_UNSUBSCRIBED_TOPIC_INDEX
}

function categoriesBlock(topicKeys: string[]): string {
    if (topicKeys.length === 0) {
        return ''
    }
    const entries = topicKeys
        .map((topicKey, index) => `        ${objectKey(topicKey)}: ${exampleSubscribed(index)},`)
        .join('\n')
    return `\n    categories: {\n${entries}\n    },`
}

export function posthogNodeSnippet({ projectToken, host, topicKeys }: AudienceSetupSnippetContext): string {
    return `import { PostHog } from 'posthog-node'

const posthog = new PostHog('${projectToken}', {
    host: '${host}',
    secretKey: process.env.POSTHOG_PERSONAL_API_KEY,
    // The key can only send preferences, so turn off feature flag polling.
    enableLocalEvaluation: false,
})

// Call this wherever a user saves their email preferences.
// Set each value from what the user picked: true subscribes, false unsubscribes.
// Leave out anything they did not change.
await posthog.messaging.setPreferences(email, {
    allMarketing: true,${categoriesBlock(topicKeys)}
})`
}

function topicKeysInstruction(topicKeys: string[]): string {
    if (topicKeys.length === 0) {
        return 'We have no topics yet, so only send `allMarketing`.'
    }
    const keys = topicKeys.map((topicKey) => `\`${topicKey}\``).join(', ')
    return `\`categories\` maps topic keys to booleans. Our topic keys are: ${keys}.`
}

export function codingAgentPrompt({ projectToken, host, topicKeys }: AudienceSetupSnippetContext): string {
    return `Send our users' email preferences to PostHog with posthog-node.

1. Install or update posthog-node to a version that has \`posthog.messaging.setPreferences\`.
2. Create a PostHog client with the project API key \`${projectToken}\`, \`host: '${host}'\`, and \`secretKey\` set to a personal API key with the \`hog_flow:write\` scope. Read the key from the POSTHOG_PERSONAL_API_KEY environment variable. Set \`enableLocalEvaluation: false\`, because this key can't fetch feature flag definitions.
3. Wherever a user saves their email preferences, call \`await posthog.messaging.setPreferences(email, { allMarketing, categories })\` with the values the user picked. Leave out anything they did not change.
   - \`allMarketing\` is a boolean. false unsubscribes the user from all marketing email, true subscribes them again.
   - ${topicKeysInstruction(topicKeys)}
4. Call it again whenever the preferences change, so PostHog always has the latest state.
5. Catch \`MessagingPreferencesError\` and log which preference failed. Retrying the whole call is safe.

Do not add any other PostHog calls as part of this change.`
}
