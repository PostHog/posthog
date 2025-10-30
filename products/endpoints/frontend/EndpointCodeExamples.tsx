import { useActions, useValues } from 'kea'

import { LemonSelect } from '@posthog/lemon-ui'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'

import { SceneSection } from '~/layout/scenes/components/SceneSection'
import { isInsightQueryNode } from '~/queries/utils'

import { CodeExampleTab, endpointLogic } from './endpointLogic'

interface EndpointCodeExamplesProps {
    tabId: string
}

function generateVariablesJson(variables: Record<string, any>): string {
    const entries = Object.entries(variables)
    if (entries.length === 0) {
        return '      // No variables defined'
    }

    return entries
        .map(([_, value], index) => {
            const isLast = index === entries.length - 1
            const comma = isLast ? '' : ','
            return `      "${value.code_name}": ${JSON.stringify(value.value)}${comma}`
        })
        .join('\n')
}

function getEndpointUrl(endpointPath: string): string {
    return `${window.location.origin}${endpointPath}`
}

function generateTerminalExample(endpointPath: string, variables: Record<string, any>): string {
    return `curl -X POST ${getEndpointUrl(endpointPath)} \\
  -H "Authorization: Bearer $POSTHOG_PERSONAL_API_KEY" \\
  -H "Content-Type: application/json" \\
  -d '{
    "variables_values": {
${generateVariablesJson(variables)}
    }
  }'`
}

function generatePythonExample(endpointPath: string, variables: Record<string, any>): string {
    return `import requests
import json

url = "${getEndpointUrl(endpointPath)}"

headers = {
    'Content-Type': 'application/json',
    'Authorization': 'Bearer {POSTHOG_PERSONAL_API_KEY}'
}

payload = {
    "variables_values": {
${generateVariablesJson(variables)}
    }
}

response = requests.post(url, headers=headers, data=json.dumps(payload))
print(response.json())`
}

function generateNodeExample(endpointPath: string, variables: Record<string, any>): string {
    return `const fetch = require('node-fetch');

const url = '${getEndpointUrl(endpointPath)}';

const headers = {
    'Content-Type': 'application/json',
    'Authorization': 'Bearer {POSTHOG_PERSONAL_API_KEY}'
};

const payload = {
    "variables_values": {
${generateVariablesJson(variables)}
    }
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

export function EndpointCodeExamples({ tabId }: EndpointCodeExamplesProps): JSX.Element {
    const { setActiveCodeExampleTab } = useActions(endpointLogic({ tabId }))
    const { activeCodeExampleTab, endpoint } = useValues(endpointLogic({ tabId }))

    if (!endpoint || isInsightQueryNode(endpoint.query)) {
        return <></>
    }

    const variables = endpoint.query.variables || {}

    const getCodeExample = (tab: CodeExampleTab): string => {
        switch (tab) {
            case 'terminal':
                return generateTerminalExample(endpoint.endpoint_path, variables)
            case 'python':
                return generatePythonExample(endpoint.endpoint_path, variables)
            case 'nodejs':
                return generateNodeExample(endpoint.endpoint_path, variables)
            default:
                return generateTerminalExample(endpoint.endpoint_path, variables)
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
        <SceneSection title="How to call this endpoint">
            <div className="flex flex-col gap-4">
                <div>
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
