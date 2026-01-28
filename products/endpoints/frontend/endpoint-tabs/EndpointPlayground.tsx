import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { IconExternal } from '@posthog/icons'
import { LemonButton, LemonDivider, LemonLabel, LemonSelect } from '@posthog/lemon-ui'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { IconPlayCircle } from 'lib/lemon-ui/icons'
import { CodeEditorInline } from 'lib/monaco/CodeEditorInline'
import { urls } from 'scenes/urls'

import { SceneSection } from '~/layout/scenes/components/SceneSection'
import { EndpointType } from '~/types'

import { CodeExampleTab, endpointLogic } from '../endpointLogic'
import { endpointSceneLogic, generateEndpointPayload } from '../endpointSceneLogic'

interface EndpointPlaygroundProps {
    tabId: string
}

function formatPayloadForCodeExample(payload: Record<string, any>): string {
    const entries = Object.entries(payload)
    if (entries.length === 0) {
        return ''
    }

    return entries
        .map(([key, value], index) => {
            const isLast = index === entries.length - 1
            const comma = isLast ? '' : ','

            // Format nested objects
            if (typeof value === 'object' && value !== null && Object.keys(value).length === 0) {
                return `    "${key}": {}${comma}  // Add ${key} here`
            }

            // Format variables specially
            if (key === 'variables' && typeof value === 'object') {
                const varEntries = Object.entries(value)
                if (varEntries.length === 0) {
                    return `    "${key}": {\n      // No variables defined\n    }${comma}`
                }
                const formattedVars = varEntries
                    .map(([varKey, varValue], varIndex) => {
                        const isLastVar = varIndex === varEntries.length - 1
                        const varComma = isLastVar ? '' : ','
                        return `      "${varKey}": ${JSON.stringify(varValue)}${varComma}`
                    })
                    .join('\n')
                return `    "${key}": {\n${formattedVars}\n    }${comma}`
            }

            return `    "${key}": ${JSON.stringify(value, null, 2).replace(/\n/g, '\n    ')}${comma}`
        })
        .join('\n')
}

function getEndpointUrl(endpointPath: string): string {
    return `${window.location.origin}${endpointPath}`
}

function generateTerminalExample(endpoint: EndpointType, selectedVersion: number | null): string {
    const payload = generateEndpointPayload(endpoint)
    const hasPayload = Object.keys(payload).length > 0
    const versionParam =
        selectedVersion !== null && selectedVersion !== endpoint.current_version
            ? `    "version": ${selectedVersion}`
            : ''

    // If no payload and no version, omit the -d flag entirely
    if (!hasPayload && !versionParam) {
        return `curl -X POST ${getEndpointUrl(endpoint.endpoint_path)} \\
  -H "Authorization: Bearer $POSTHOG_PERSONAL_API_KEY"`
    }

    const payloadBody = formatPayloadForCodeExample(payload)
    const dataContent = [payloadBody, versionParam].filter(Boolean).join(',\n')

    return `curl -X POST ${getEndpointUrl(endpoint.endpoint_path)} \\
  -H "Authorization: Bearer $POSTHOG_PERSONAL_API_KEY" \\
  -H "Content-Type: application/json" \\
  -d '{
${dataContent}
  }'`
}

function generatePythonExample(endpoint: EndpointType, selectedVersion: number | null): string {
    const payload = generateEndpointPayload(endpoint)
    const hasPayload = Object.keys(payload).length > 0
    const versionParam =
        selectedVersion !== null && selectedVersion !== endpoint.current_version
            ? `    "version": ${selectedVersion}`
            : ''

    // If no payload and no version, omit payload variable entirely
    if (!hasPayload && !versionParam) {
        return `import requests

url = "${getEndpointUrl(endpoint.endpoint_path)}"

headers = {
    'Authorization': 'Bearer {POSTHOG_PERSONAL_API_KEY}'
}

response = requests.post(url, headers=headers)
print(response.json())`
    }

    const payloadBody = formatPayloadForCodeExample(payload)
    const dataContent = [payloadBody, versionParam].filter(Boolean).join(',\n')

    return `import requests
import json

url = "${getEndpointUrl(endpoint.endpoint_path)}"

headers = {
    'Content-Type': 'application/json',
    'Authorization': 'Bearer {POSTHOG_PERSONAL_API_KEY}'
}

payload = {
${dataContent}
}

response = requests.post(url, headers=headers, data=json.dumps(payload))
print(response.json())`
}

function generateNodeExample(endpoint: EndpointType, selectedVersion: number | null): string {
    const payload = generateEndpointPayload(endpoint)
    const hasPayload = Object.keys(payload).length > 0
    const versionParam =
        selectedVersion !== null && selectedVersion !== endpoint.current_version
            ? `    "version": ${selectedVersion}`
            : ''

    // If no payload and no version, omit payload variable and body entirely
    if (!hasPayload && !versionParam) {
        return `const fetch = require('node-fetch');

const url = '${getEndpointUrl(endpoint.endpoint_path)}';

const headers = {
    'Authorization': 'Bearer {POSTHOG_PERSONAL_API_KEY}'
};

fetch(url, {
    method: 'POST',
    headers: headers
})
.then(response => response.json())
.then(data => console.log(data))
.catch(error => console.error('Error:', error));`
    }

    const payloadBody = formatPayloadForCodeExample(payload)
    const dataContent = [payloadBody, versionParam].filter(Boolean).join(',\n')

    return `const fetch = require('node-fetch');

const url = '${getEndpointUrl(endpoint.endpoint_path)}';

const headers = {
    'Content-Type': 'application/json',
    'Authorization': 'Bearer {POSTHOG_PERSONAL_API_KEY}'
};

const payload = {
${dataContent}
};

fetch(url, {
    method: 'POST',
    headers: headers,
    body: JSON.stringify(payload)
})
.then(response => response.json())
.then(data => console.log(data))
.catch(error => console.error('Error:', error));`
}

export function EndpointPlayground({ tabId }: EndpointPlaygroundProps): JSX.Element {
    const { endpoint } = useValues(endpointLogic({ tabId }))
    const { payloadJson, payloadJsonError, endpointResult, endpointResultLoading } = useValues(
        endpointSceneLogic({ tabId })
    )
    const { setPayloadJson, setPayloadJsonError, loadEndpointResult } = useActions(endpointSceneLogic({ tabId }))
    const { setActiveCodeExampleTab, setSelectedCodeExampleVersion } = useActions(endpointLogic({ tabId }))
    const { activeCodeExampleTab, selectedCodeExampleVersion } = useValues(endpointLogic({ tabId }))

    const handleExecute = (): void => {
        if (!endpoint?.name) {
            return
        }

        let data: any = {}
        try {
            data = payloadJson && payloadJson.trim() !== '' ? JSON.parse(payloadJson) : {}
        } catch {
            setPayloadJsonError('Invalid JSON in request payload')
            return
        }

        loadEndpointResult({ name: endpoint.name, data })
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
    }, [endpoint?.name, payloadJson, handleExecute])

    if (!endpoint) {
        return <></>
    }

    const getCodeExample = (tab: CodeExampleTab): string => {
        switch (tab) {
            case 'terminal':
                return generateTerminalExample(endpoint, selectedCodeExampleVersion)
            case 'python':
                return generatePythonExample(endpoint, selectedCodeExampleVersion)
            case 'nodejs':
                return generateNodeExample(endpoint, selectedCodeExampleVersion)
            default:
                return generateTerminalExample(endpoint, selectedCodeExampleVersion)
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

    // Generate version options
    const versionOptions = Array.from({ length: endpoint.current_version }, (_, i) => {
        const version = i + 1
        return {
            value: version,
            label: version === endpoint.current_version ? `v${version} (Current)` : `v${version}`,
        }
    })

    return (
        <SceneSection
            title="Playground"
            description={
                <>
                    Send API requests to your endpoints, play with setting different parameters in the request body and
                    see what the resulting JSON response would look like. <br />
                    Once you're done experimenting, find the code snippet for your use case below.
                </>
            }
        >
            <div className="flex gap-4" data-attr="endpoint-playground">
                <div className="flex-1 flex flex-col gap-2">
                    <LemonField.Pure
                        label="Request payload"
                        info={
                            <>
                                JSON payload sent with the request. Use <code className="text-xs">"variables"</code> to
                                pass query parameters.
                            </>
                        }
                    />

                    <CodeEditorInline
                        embedded
                        language="json"
                        value={payloadJson}
                        onChange={(value) => setPayloadJson(value ?? '')}
                        maxHeight={400}
                    />
                    {payloadJsonError && <LemonField.Pure error={payloadJsonError} />}

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
                        options={versionOptions}
                        onChange={setSelectedCodeExampleVersion}
                        value={selectedCodeExampleVersion || endpoint.current_version}
                        placeholder="Select version"
                    />
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
                        API keys
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
