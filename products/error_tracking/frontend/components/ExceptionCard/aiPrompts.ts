import { urls } from 'scenes/urls'

function issueUrl(issueId: string): string {
    return window.location.origin + urls.errorTrackingIssue(issueId)
}

export function buildFixPrompt(stacktraceText: string, issueId: string): string {
    return `Please help me fix the root cause of this error. Here's the stack trace:

\`\`\`
${stacktraceText}
\`\`\`

Note: Frames marked with [IN-APP] are from the application code (my code), while frames without this marker are from external libraries/frameworks.
Focus your analysis primarily on the [IN-APP] frames as these are most likely where the issue needs to be fixed.

Can you:
1. Gather relevant information from the codebase to understand the context of this error.
2. Inspect the code paths involved to identify the root cause.
3. Determine the simplest and cleanest fix for this issue.
4. Implement the fix directly in the codebase.

The final output of your efforts should be:
- An implemented fix for the issue applied directly to the code
- A brief explanation of what was changed and why

PostHog issue: ${issueUrl(issueId)}
`
}

export function buildExplainPrompt(stacktraceText: string, issueId: string): string {
    return `Please help me understand this error in depth. Here's the stack trace:

\`\`\`
${stacktraceText}
\`\`\`

Note: Frames marked with [IN-APP] are from the application code (my code), while frames without this marker are from external libraries/frameworks.
Focus your analysis primarily on the [IN-APP] frames as these are most likely where the issue originates.

Can you:
1. Perform a deep dive analysis into what's causing this error. Consider multiple possible factors and dig deep to find the root cause.
2. Explain the relevant parts of the code that are involved in this error. Walk through the execution flow that leads to this issue.
3. Provide a detailed explanation of exactly how this issue happened, including the sequence of events and conditions that trigger it.
4. Include code examples and context where helpful to illustrate your explanation.

The final output should be:
- A comprehensive technical explanation of the root cause
- A walkthrough of the relevant code paths
- A detailed summary of exactly how the issue occurs

PostHog issue: ${issueUrl(issueId)}
`
}
