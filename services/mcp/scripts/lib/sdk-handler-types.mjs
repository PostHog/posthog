import fs from 'node:fs'
import path from 'node:path'
import ts from 'typescript'

/** Read result contracts before the MCP registry erases each factory's generic result type. */
export function readHandlerResultTypes(repoRoot) {
    const directory = path.join(repoRoot, 'services/mcp')
    const config = ts.readConfigFile(path.join(directory, 'tsconfig.json'), ts.sys.readFile)
    const parsed = ts.parseJsonConfigFileContent(config.config, ts.sys, directory)
    const roots = [
        path.join(directory, 'src/tools/index.ts'),
        ...fs
            .readdirSync(path.join(directory, 'src/tools/generated'))
            .filter((name) => name.endsWith('.ts'))
            .map((name) => path.join(directory, 'src/tools/generated', name)),
    ]
    const program = ts.createProgram(roots, { ...parsed.options, types: ['node'], noEmit: true })
    const checker = program.getTypeChecker()
    const handlers = new Map()
    for (const file of roots) {
        const source = program.getSourceFile(file)
        const visit = (node) => {
            if (
                ts.isVariableDeclaration(node) &&
                ['GENERATED_TOOLS', 'TOOL_MAP'].includes(node.name.getText()) &&
                node.initializer &&
                ts.isObjectLiteralExpression(node.initializer)
            ) {
                for (const property of node.initializer.properties) {
                    if (!ts.isPropertyAssignment(property)) {
                        continue
                    }
                    const key = ts.isComputedPropertyName(property.name)
                        ? checker.getTypeAtLocation(property.name.expression).value
                        : property.name.text
                    const factory = checker.getTypeAtLocation(property.initializer).getCallSignatures()[0]
                    if (!key || !factory) {
                        continue
                    }
                    const tool = factory.getReturnType()
                    const handler = tool.getProperty('handler')
                    if (!handler) {
                        throw new Error(`No handler type for ${key}`)
                    }
                    const signature = checker.getTypeOfSymbolAtLocation(handler, property).getCallSignatures()[0]
                    const type = checker.getAwaitedType(signature.getReturnType())
                    handlers.set(key, { type, file: path.relative(repoRoot, file) })
                }
            }
            ts.forEachChild(node, visit)
        }
        visit(source)
    }

    return (toolName) => {
        const found = handlers.get(toolName)
        if (!found) {
            return undefined
        }
        const definitions = {}
        const visited = new Map()
        const convert = (type) => {
            if (!type || type.flags & (ts.TypeFlags.Any | ts.TypeFlags.Unknown)) {
                return {
                    description:
                        'The MCP handler declares this value as arbitrary JSON. Its fields depend on the requested resource.',
                }
            }
            if (type.flags & (ts.TypeFlags.Undefined | ts.TypeFlags.Void | ts.TypeFlags.Null | ts.TypeFlags.Never)) {
                return { type: 'null' }
            }
            if (type.flags & ts.TypeFlags.StringLiteral) {
                return { type: 'string', const: type.value }
            }
            if (type.flags & ts.TypeFlags.NumberLiteral) {
                return { type: 'number', const: type.value }
            }
            if (type.flags & ts.TypeFlags.BooleanLiteral) {
                return { type: 'boolean', const: type.intrinsicName === 'true' }
            }
            if (type.flags & ts.TypeFlags.StringLike) {
                return { type: 'string' }
            }
            if (type.flags & ts.TypeFlags.NumberLike) {
                return { type: 'number' }
            }
            if (type.flags & ts.TypeFlags.BooleanLike) {
                return { type: 'boolean' }
            }
            if (type.isUnion()) {
                const members = type.types.filter((part) => !(part.flags & ts.TypeFlags.Undefined))
                if (members.length === 1) {
                    return convert(members[0])
                }
                const variants = members.map(convert)
                if (variants.every((part) => part.type === 'boolean')) {
                    return { type: 'boolean' }
                }
                return { anyOf: variants }
            }
            if (checker.isArrayType(type) || checker.isTupleType(type)) {
                const items = checker.getTypeArguments(type)
                return { type: 'array', items: items.length > 1 ? { anyOf: items.map(convert) } : convert(items[0]) }
            }
            if (visited.has(type)) {
                return { $ref: `#/definitions/${visited.get(type)}` }
            }
            const name = `Shape${visited.size + 1}`
            visited.set(type, name)
            const schema = { type: 'object', properties: {}, required: [] }
            definitions[name] = schema
            const docs =
                type.aliasSymbol?.getDocumentationComment(checker) ?? type.getSymbol()?.getDocumentationComment(checker)
            if (docs?.length) {
                schema.description = ts.displayPartsToString(docs)
            }
            for (const property of type.getProperties()) {
                if (property.name.startsWith('__@')) {
                    continue
                }
                const declaration = property.valueDeclaration ?? property.declarations?.[0]
                const propertyType = checker.getTypeOfSymbolAtLocation(
                    property,
                    declaration ?? found.type.symbol?.valueDeclaration
                )
                const field = convert(propertyType)
                const description = ts.displayPartsToString(property.getDocumentationComment(checker))
                schema.properties[property.name] = description ? { ...field, description } : field
                if (!(property.flags & ts.SymbolFlags.Optional)) {
                    schema.required.push(property.name)
                }
            }
            const index = type.getStringIndexType()
            if (index) {
                schema.additionalProperties = convert(index)
            }
            return { $ref: `#/definitions/${name}` }
        }
        return { schema: convert(found.type), definitions, file: found.file }
    }
}
