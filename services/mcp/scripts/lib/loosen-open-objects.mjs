import ts from 'typescript'

export function collectOpenObjectPaths(schema) {
    const openPathsByExport = new Map()
    for (const methods of Object.values(schema.paths ?? {})) {
        for (const operation of Object.values(methods ?? {})) {
            const bodySchema = operation?.requestBody?.content?.['application/json']?.schema
            if (!bodySchema || !operation.operationId) {
                continue
            }
            const openPaths = new Set()
            collectFrom(bodySchema, schema, [], openPaths, new Set())
            if (openPaths.size > 0) {
                openPathsByExport.set(`${pascalCase(operation.operationId)}Body`, openPaths)
            }
        }
    }
    return openPathsByExport
}

export function loosenOpenObjects(source, openPathsByExport) {
    if (openPathsByExport.size === 0) {
        return source
    }
    const sourceFile = ts.createSourceFile('api.ts', source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TS)
    const edits = []

    const visit = (node, path, openPaths) => {
        if (ts.isPropertyAssignment(node)) {
            const propertyPath = [...path, node.name.text]
            markIfOpen(node.initializer, propertyPath, openPaths, edits)
            ts.forEachChild(node.initializer, (child) => visit(child, propertyPath, openPaths))
            return
        }
        ts.forEachChild(node, (child) => visit(child, path, openPaths))
    }

    for (const statement of sourceFile.statements) {
        if (!ts.isVariableStatement(statement)) {
            continue
        }
        for (const declaration of statement.declarationList.declarations) {
            const openPaths = ts.isIdentifier(declaration.name) && openPathsByExport.get(declaration.name.text)
            if (!openPaths || !declaration.initializer) {
                continue
            }
            markIfOpen(declaration.initializer, [], openPaths, edits)
            visit(declaration.initializer, [], openPaths)
        }
    }

    return edits
        .sort((a, b) => b.start - a.start)
        .reduce((text, { start, end }) => `${text.slice(0, start)}looseObject${text.slice(end)}`, source)
}

function collectFrom(node, schema, path, openPaths, ancestors) {
    const resolved = resolveRef(node, schema)
    if (!resolved || typeof resolved !== 'object' || ancestors.has(resolved)) {
        return
    }
    ancestors.add(resolved)
    if (resolved.properties && resolved.additionalProperties === true) {
        openPaths.add(path.join('.'))
    }
    for (const member of [...(resolved.allOf ?? []), ...(resolved.anyOf ?? []), ...(resolved.oneOf ?? [])]) {
        collectFrom(member, schema, path, openPaths, ancestors)
    }
    if (resolved.items) {
        collectFrom(resolved.items, schema, path, openPaths, ancestors)
    }
    for (const [key, property] of Object.entries(resolved.properties ?? {})) {
        collectFrom(property, schema, [...path, key], openPaths, ancestors)
    }
    ancestors.delete(resolved)
}

function resolveRef(node, schema) {
    let resolved = node
    while (resolved?.$ref) {
        resolved = schema.components?.schemas?.[resolved.$ref.split('/').pop()]
    }
    return resolved
}

function markIfOpen(expression, path, openPaths, edits) {
    if (!openPaths.has(path.join('.'))) {
        return
    }
    let current = expression
    while (ts.isCallExpression(current) || ts.isPropertyAccessExpression(current)) {
        if (ts.isPropertyAccessExpression(current) && current.name.text === 'strictObject') {
            edits.push({ start: current.name.getStart(), end: current.name.getEnd() })
            return
        }
        current = current.expression
    }
}

function pascalCase(operationId) {
    return operationId
        .split(/[_.]/)
        .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
        .join('')
}
