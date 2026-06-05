import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { IconExternal } from '@posthog/icons'
import { LemonButton, LemonDivider, LemonLabel, LemonSelect } from '@posthog/lemon-ui'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { IconPlayCircle } from 'lib/lemon-ui/icons'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { CodeEditorInline } from 'lib/monaco/CodeEditorInline'
import { urls } from 'scenes/urls'

import { SceneSection } from '~/layout/scenes/components/SceneSection'
import { EndpointRunRequest } from '~/queries/schema/schema-general'
import { EndpointType } from '~/types'

import { CodeExampleTab, endpointLogic } from '../endpointLogic'
import { endpointSceneLogic } from '../endpointSceneLogic'
import { EndpointPlaygroundForm } from './EndpointPlaygroundForm'
import { EndpointPlaygroundJSONPreview } from './EndpointPlaygroundJSONPreview'

function getEndpointUrl(endpointPath: string): string {
    return `${window.location.origin}${endpointPath}`
}

/**
 * Code example formatting. These render the *live* playground payload — so the snippet a
 * user copies always matches what the form would POST. No silent reseeding from defaults.
 */
function formatBodyJson(payload: EndpointRunRequest, indent: number): string {
    if (Object.keys(payload).length === 0) {
        return ''
    }
    return JSON.stringify(payload, null, 2)
        .split('\n')
        .map((line, i) => (i === 0 ? line : ' '.repeat(indent) + line))
        .join('\n')
}

function generateTerminalExample(endpoint: EndpointType, payload: EndpointRunRequest): string {
    const url = getEndpointUrl(endpoint.endpoint_path)
    if (Object.keys(payload).length === 0) {
        return `curl -X POST ${url} \\
  -H "Authorization: Bearer $POSTHOG_PERSONAL_API_KEY"`
    }
    return `curl -X POST ${url} \\
  -H "Authorization: Bearer $POSTHOG_PERSONAL_API_KEY" \\
  -H "Content-Type: application/json" \\
  -d '${formatBodyJson(payload, 2)}'`
}

function generatePythonExample(endpoint: EndpointType, payload: EndpointRunRequest): string {
    const url = getEndpointUrl(endpoint.endpoint_path)
    if (Object.keys(payload).length === 0) {
        return `import requests

url = "${url}"

headers = {
    'Authorization': 'Bearer {POSTHOG_PERSONAL_API_KEY}'
}

response = requests.post(url, headers=headers)
print(response.json())`
    }
    return `import requests

url = "${url}"

headers = {
    'Content-Type': 'application/json',
    'Authorization': 'Bearer {POSTHOG_PERSONAL_API_KEY}'
}

payload = ${formatBodyJson(payload, 0)}

response = requests.post(url, headers=headers, json=payload)
print(response.json())`
}

function generateNodeExample(endpoint: EndpointType, payload: EndpointRunRequest): string {
    const url = getEndpointUrl(endpoint.endpoint_path)
    if (Object.keys(payload).length === 0) {
        return `const fetch = require('node-fetch');

const url = '${url}';

const headers = {
    'Authorization': 'Bearer {POSTHOG_PERSONAL_API_KEY}'
};

fetch(url, { method: 'POST', headers })
    .then((response) => response.json())
    .then((data) => console.log(data))
    .catch((error) => console.error('Error:', error));`
    }
    return `const fetch = require('node-fetch');

const url = '${url}';

const headers = {
    'Content-Type': 'application/json',
    'Authorization': 'Bearer {POSTHOG_PERSONAL_API_KEY}'
};

const payload = ${formatBodyJson(payload, 0)};

fetch(url, { method: 'POST', headers, body: JSON.stringify(payload) })
    .then((response) => response.json())
    .then((data) => console.log(data))
    .catch((error) => console.error('Error:', error));`
}

export function EndpointPlayground(): JSX.Element {
    const { endpoint } = useValues(endpointLogic)
    const { endpointResult, endpointResultLoading, playgroundPayload } = useValues(endpointSceneLogic)
    const { loadEndpointResult, setPlaygroundExecutionError } = useActions(endpointSceneLogic)
    const { setActiveCodeExampleTab } = useActions(endpointLogic)
    const { activeCodeExampleTab } = useValues(endpointLogic)

    const handleExecute = (): void => {
        if (!endpoint?.name) {
            return
        }
        // playgroundPayload already incorporates debug via the selector; no need to re-merge.
        // Clear any prior per-variable error so a successful execution wipes the red border.
        setPlaygroundExecutionError(null)
        loadEndpointResult({ name: endpoint.name, data: playgroundPayload })
    }

    useEffect(() => {
        const handleKeyDown = (e: KeyboardEvent): void => {
            if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {
                e.preventDefault()
                e.stopPropagation()
                handleExecute()
            }
        }

        window.addEventListener('keydown', handleKeyDown, true)
        return () => window.removeEventListener('keydown', handleKeyDown, true)
    }, [endpoint?.name, playgroundPayload, handleExecute])

    // Detect Required-variable failures coming back from the server and route them to the
    // matching variable input — the user gets a red border on the input that actually needs
    // a value instead of a generic page-level banner.
    useEffect(() => {
        if (!endpointResult || endpointResultLoading) {
            return
        }
        try {
            const parsed = JSON.parse(endpointResult)
            if (parsed?.error && typeof parsed.detail === 'string') {
                if (parsed.detail.includes('Required variable')) {
                    setPlaygroundExecutionError(parsed.detail)
                }
            }
        } catch {
            // Not JSON or no error — nothing to surface.
        }
    }, [endpointResult, endpointResultLoading, setPlaygroundExecutionError])

    if (!endpoint) {
        return <></>
    }

    const getCodeExample = (tab: CodeExampleTab): string => {
        switch (tab) {
            case 'terminal':
                return generateTerminalExample(endpoint, playgroundPayload)
            case 'python':
                return generatePythonExample(endpoint, playgroundPayload)
            case 'nodejs':
                return generateNodeExample(endpoint, playgroundPayload)
            default:
                return generateTerminalExample(endpoint, playgroundPayload)
        }
    }

    const getLanguage = (tab: CodeExampleTab): Language => {
        switch (tab) {
            case 'terminal':
                return Language.Bash
            case 'python':
                return Language.Python
            case 'nodejs':
                return Language.JavaScript
            default:
                return Language.Bash
        }
    }

    return (
        <SceneSection
            title="Playground"
            description={
                <>
                    Pick variable values and request options below, then execute against this endpoint to see what /run
                    returns. The code snippet below mirrors the request the form would send.
                </>
            }
        >
            <div className="flex gap-4" data-attr="endpoint-playground">
                <div className="flex-1 flex flex-col gap-3 min-w-0">
                    <EndpointPlaygroundForm />
                    <EndpointPlaygroundJSONPreview />
                    <div className="flex items-center gap-2">
                        <LemonButton
                            type="primary"
                            size="small"
                            icon={<IconPlayCircle />}
                            onClick={handleExecute}
                            loading={endpointResultLoading}
                            tooltip="Cmd/Ctrl + Enter"
                            disabledReason={
                                !endpoint?.is_active
                                    ? 'This endpoint is inactive. Activate it in the actions panel on the top right to execute.'
                                    : undefined
                            }
                        >
                            Execute endpoint
                        </LemonButton>
                    </div>
                    {endpointResult &&
                        !endpointResultLoading &&
                        (() => {
                            try {
                                const parsed = JSON.parse(endpointResult)
                                if (
                                    'results' in parsed &&
                                    Array.isArray(parsed.results) &&
                                    parsed.results.length === 0
                                ) {
                                    return <LemonField.Pure error="No results" />
                                }
                            } catch {
                                // Invalid JSON, don't show anything
                            }
                            return null
                        })()}
                </div>

                <div className="flex-3 flex flex-col gap-2">
                    <LemonField.Pure
                        label="API response"
                        info={
                            <>
                                API response from the endpoint. Pay attention to the{' '}
                                <code className="text-xs">"results"</code> key in the JSON below.
                            </>
                        }
                    />
                    <CodeEditorInline
                        embedded
                        language="json"
                        value={endpointResult || 'Execute endpoint to see API response.'}
                        maxHeight={400}
                        options={{
                            readOnly: true,
                            lineNumbers: 'on',
                            folding: true,
                            foldingStrategy: 'indentation',
                            showFoldingControls: 'always',
                        }}
                    />
                </div>
            </div>
            <LemonDivider className="my-4" />
            <div className="flex flex-col gap-4">
                <LemonLabel info="Create a personal API key and copy a code example to call this endpoint from your application.">
                    Example usage
                </LemonLabel>
                <div className="flex gap-2">
                    <LemonSelect
                        options={[
                            { value: 'terminal', label: 'Terminal' },
                            { value: 'python', label: 'Python' },
                            { value: 'nodejs', label: 'Node.js' },
                        ]}
                        onChange={(val) => {
                            if (val) {
                                setActiveCodeExampleTab(val as CodeExampleTab)
                            }
                        }}
                        value={activeCodeExampleTab}
                    />
                    <LemonButton
                        to={urls.settings('user', 'personal-api-keys')}
                        type="secondary"
                        size="small"
                        icon={<IconExternal />}
                        targetBlank
                    >
                        Create a Personal API Key
                    </LemonButton>
                </div>
                <div>
                    <CodeSnippet language={getLanguage(activeCodeExampleTab)} wrap={true}>
                        {getCodeExample(activeCodeExampleTab)}
                    </CodeSnippet>
                </div>
            </div>
        </SceneSection>
    )
}
