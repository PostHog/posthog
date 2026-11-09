import type { CodeEmailApi } from 'products/messaging/frontend/generated/api.schemas'

import { parseSourceFile } from './sourceFile'

/** A prompt a person pastes into their coding agent to change an email their code sends. */
export function agentPrompt(codeEmail: CodeEmailApi): string {
    const file = codeEmail.source_url ? parseSourceFile(codeEmail.source_url) : null
    return [
        `Change the "${codeEmail.key}" email that our code sends through PostHog.`,
        file
            ? `It is built in ${file.path}${file.repo ? ` in ${file.repo}` : ''}.`
            : `Find the code that sends it with the template_key "${codeEmail.key}".`,
        'Keep the template_key the same, so its metrics and sends stay on one email in PostHog.',
    ].join(' ')
}
