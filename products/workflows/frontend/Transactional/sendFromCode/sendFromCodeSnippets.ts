export type SendFromCodeSdk = 'node' | 'python' | 'curl'

export interface SendFromCodeSnippetInput {
    projectToken: string
    host: string
    appHost: string | null
    sendUrl: string
    from: string | null
}

export interface SendFromCodeSnippet {
    install: string | null
    code: string
}

const INSTALL_FROM_FIRST_VERSION_WITH_CODE_SENDS: Record<SendFromCodeSdk, string | null> = {
    node: 'npm install posthog-node@6',
    python: 'pip install posthog~=8.0',
    curl: null,
}

const EXAMPLE = {
    templateKey: 'welcome',
    to: 'jane@example.com',
    distinctId: 'jane-distinct-id',
    subject: 'Welcome to Acme',
    html: '<p>Hi Jane, thanks for signing up.</p>',
    idempotencyKey: 'welcome-jane-distinct-id',
}

const shellSingleQuoted = (value: string): string => `'${value.replace(/'/g, `'\\''`)}'`

function nodeSnippet({ projectToken, host, appHost, from }: SendFromCodeSnippetInput): string {
    return `import { PostHog } from 'posthog-node'

const posthog = new PostHog(${JSON.stringify(projectToken)}, {
    host: ${JSON.stringify(host)},${appHost ? `\n    appHost: ${JSON.stringify(appHost)},` : ''}
    secretKey: process.env.POSTHOG_PROJECT_SECRET_API_KEY,
    // Sends email only, so skip polling flag definitions
    enableLocalEvaluation: false,
})

const { data, error } = await posthog.emails.send({
    templateKey: ${JSON.stringify(EXAMPLE.templateKey)},
    to: ${JSON.stringify(EXAMPLE.to)},
    distinctId: ${JSON.stringify(EXAMPLE.distinctId)},${from ? `\n    from: ${JSON.stringify(from)},` : ''}
    subject: ${JSON.stringify(EXAMPLE.subject)},
    html: ${JSON.stringify(EXAMPLE.html)},
    idempotencyKey: ${JSON.stringify(EXAMPLE.idempotencyKey)},
})
if (error) {
    throw error
}
console.log(data.id)`
}

function pythonSnippet({ projectToken, host, appHost, from }: SendFromCodeSnippetInput): string {
    return `import os

from posthog import Posthog

posthog = Posthog(
    ${JSON.stringify(projectToken)},
    host=${JSON.stringify(host)},${appHost ? `\n    app_host=${JSON.stringify(appHost)},` : ''}
    secret_key=os.environ["POSTHOG_PROJECT_SECRET_API_KEY"],
)

result = posthog.emails.send(
    template_key=${JSON.stringify(EXAMPLE.templateKey)},
    to=${JSON.stringify(EXAMPLE.to)},
    distinct_id=${JSON.stringify(EXAMPLE.distinctId)},${from ? `\n    from_=${JSON.stringify(from)},` : ''}
    subject=${JSON.stringify(EXAMPLE.subject)},
    html=${JSON.stringify(EXAMPLE.html)},
    idempotency_key=${JSON.stringify(EXAMPLE.idempotencyKey)},
)
print(result.id)`
}

function curlSnippet({ sendUrl, from }: SendFromCodeSnippetInput): string {
    const body = {
        template_key: EXAMPLE.templateKey,
        to: EXAMPLE.to,
        distinct_id: EXAMPLE.distinctId,
        ...(from ? { from } : {}),
        subject: EXAMPLE.subject,
        html: EXAMPLE.html,
    }
    return `curl -X POST ${sendUrl} \\
  -H "Authorization: Bearer $POSTHOG_PROJECT_SECRET_API_KEY" \\
  -H "Content-Type: application/json" \\
  -H "Idempotency-Key: ${EXAMPLE.idempotencyKey}" \\
  -d ${shellSingleQuoted(JSON.stringify(body, null, 2))}`
}

const BUILDERS: Record<SendFromCodeSdk, (input: SendFromCodeSnippetInput) => string> = {
    node: nodeSnippet,
    python: pythonSnippet,
    curl: curlSnippet,
}

export function sendFromCodeSnippet(sdk: SendFromCodeSdk, input: SendFromCodeSnippetInput): SendFromCodeSnippet {
    return { install: INSTALL_FROM_FIRST_VERSION_WITH_CODE_SENDS[sdk], code: BUILDERS[sdk](input) }
}
