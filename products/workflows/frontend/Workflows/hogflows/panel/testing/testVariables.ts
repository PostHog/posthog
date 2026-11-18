export function parseTestVariables(value: string = '{}'): Record<string, any> {
    const variables: unknown = JSON.parse(value)
    if (!variables || typeof variables !== 'object' || Array.isArray(variables)) {
        throw new Error('Enter variables as a JSON object')
    }
    return variables as Record<string, any>
}

export function testVariablesError(value: string = '{}'): string | undefined {
    try {
        parseTestVariables(value)
    } catch {
        return 'Enter variables as a JSON object, for example {"name": "Alex"}'
    }
}
