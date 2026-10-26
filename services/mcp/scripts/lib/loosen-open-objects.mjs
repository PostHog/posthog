import ts from 'typescript'

export function collectOpenObjectPaths(schema, moduleName) {
    const targetsByExport = new Map()
    for (const methods of Object.values(schema.paths ?? {})) {
        for (const operation of Object.values(methods ?? {})) {
            const bodySchema = operation?.requestBody?.content?.['application/json']?.schema
            if (!bodySchema || !operation.operationId) {
                continue
            }
            const target = { moduleName, operationId: operation.operationId, paths: new Set() }
            collectFrom(bodySchema, schema, [], false, target, new Set())
            if (target.paths.size > 0) {
                targetsByExport.set(`${pascalCase(operation.operationId)}Body`, target)
            }
        }
    }
    return targetsByExport
}

export function loosenOpenObjects(source, targetsByExport) {
    if (targetsByExport.size === 0) {
        return source
    }
    const sourceFile = ts.createSourceFile('api.ts', source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TS)
    const edits = []
    const placedByExport = new Map([...targetsByExport.keys()].map((exportName) => [exportName, new Set()]))

    for (const statement of sourceFile.statements) {
        if (!ts.isVariableStatement(statement)) {
            continue
        }
        for (const declaration of statement.declarationList.declarations) {
            const exportName = ts.isIdentifier(declaration.name) ? declaration.name.text : undefined
            const target = targetsByExport.get(exportName)
            if (!target || !declaration.initializer) {
                continue
            }
            const place = (expression, path) => {
                const joinedPath = path.join('.')
                if (target.paths.has(joinedPath) && placeObject(expression, edits)) {
                    placedByExport.get(exportName).add(joinedPath)
                }
            }
            place(declaration.initializer, [])
            visitProperties(declaration.initializer, [], place)
        }
    }

    for (const [exportName, target] of targetsByExport) {
        const unplacedPath = [...target.paths].find((path) => !placedByExport.get(exportName).has(path))
        if (unplacedPath !== undefined) {
            throw targetError(target, unplacedPath, `matches no generated object in ${exportName}`)
        }
    }

    return edits
        .sort((a, b) => b.start - a.start)
        .reduce((text, { start, end }) => `${text.slice(0, start)}looseObject${text.slice(end)}`, source)
}

function collectFrom(node, schema, path, underUnion, target, ancestors) {
    const resolved = resolveRef(node, schema)
    if (!resolved || typeof resolved !== 'object' || ancestors.has(resolved)) {
        return
    }
    ancestors.add(resolved)
    if (resolved.properties && resolved.additionalProperties === true) {
        addOpenPath(target, path, underUnion)
    }
    for (const member of resolved.allOf ?? []) {
        collectFrom(member, schema, path, underUnion, target, ancestors)
    }
    const unionMembers = [...(resolved.anyOf ?? []), ...(resolved.oneOf ?? [])]
    const isRealUnion = withoutNull(unionMembers, schema).length > 1
    for (const member of unionMembers) {
        collectFrom(member, schema, path, underUnion || isRealUnion, target, ancestors)
    }
    if (resolved.items) {
        collectFrom(resolved.items, schema, path, underUnion, target, ancestors)
    }
    for (const [key, property] of Object.entries(resolved.properties ?? {})) {
        collectFrom(property, schema, [...path, key], underUnion, target, ancestors)
    }
    ancestors.delete(resolved)
}

function addOpenPath(target, path, underUnion) {
    const joinedPath = path.join('.')
    if (underUnion) {
        throw targetError(target, joinedPath, 'sits under oneOf or anyOf')
    }
    if (path.some((key) => key.includes('.'))) {
        throw targetError(target, joinedPath, 'has a property name with a dot')
    }
    if (target.paths.has(joinedPath)) {
        throw targetError(target, joinedPath, 'is opened by more than one schema branch')
    }
    target.paths.add(joinedPath)
}

function targetError(target, path, reason) {
    return new Error(
        `loosen-open-objects: ${target.moduleName} ${target.operationId} open object at "${path || '<body>'}" ${reason}`
    )
}

function withoutNull(members, schema) {
    return members.filter((member) => resolveRef(member, schema)?.type !== 'null')
}

function resolveRef(node, schema) {
    let resolved = node
    while (resolved?.$ref) {
        resolved = schema.components?.schemas?.[resolved.$ref.split('/').pop()]
    }
    return resolved
}

function visitProperties(node, path, place) {
    if (ts.isPropertyAssignment(node)) {
        const propertyPath = [...path, node.name.text]
        place(node.initializer, propertyPath)
        ts.forEachChild(node.initializer, (child) => visitProperties(child, propertyPath, place))
        return
    }
    ts.forEachChild(node, (child) => visitProperties(child, path, place))
}

function placeObject(expression, edits) {
    let current = expression
    while (ts.isCallExpression(current) || ts.isPropertyAccessExpression(current)) {
        if (ts.isPropertyAccessExpression(current) && current.name.text === 'looseObject') {
            return true
        }
        if (ts.isPropertyAccessExpression(current) && current.name.text === 'strictObject') {
            edits.push({ start: current.name.getStart(), end: current.name.getEnd() })
            return true
        }
        current = current.expression
    }
    return false
}

function pascalCase(operationId) {
    return operationId
        .split(/[_.]/)
        .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
        .join('')
}
