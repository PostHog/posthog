export function pascalCase(value) {
    return value.replace(/(^|[-_.])([a-z])/g, (_, _separator, letter) => letter.toUpperCase())
}

export function annotateDocumentation(value, source, pointer = '#') {
    if (!value || typeof value !== 'object') {
        return
    }
    for (const [key, child] of Object.entries(value)) {
        annotateDocumentation(child, source, `${pointer}/${key.replace(/~/g, '~0').replace(/\//g, '~1')}`)
    }
    if (typeof value.description === 'string' && !value['x-documentation-source']) {
        value['x-documentation-source'] = { ...source, pointer }
    }
}

export function resolveRef(spec, schema, seen = new Set()) {
    if (!schema?.$ref) {
        return schema
    }
    const ref = schema.$ref
    if (!ref.startsWith('#/') || seen.has(ref)) {
        throw new Error(`Cannot resolve schema reference ${ref}`)
    }
    const target = ref
        .slice(2)
        .split('/')
        .reduce((node, key) => node?.[key.replace(/~1/g, '/').replace(/~0/g, '~')], spec)
    if (!target) {
        throw new Error(`Missing schema reference ${ref}`)
    }
    const { $ref, ...siblings } = schema
    return { ...resolveRef(spec, target, new Set([...seen, ref])), ...siblings }
}

export function objectSchema(spec, node) {
    const schema = resolveRef(spec, node)
    if (!schema?.allOf) {
        return schema
    }
    const { allOf, ...base } = schema
    if (allOf.length === 1 && !base.properties) {
        return { ...objectSchema(spec, allOf[0]), ...base }
    }
    const parts = [...allOf.map((part) => objectSchema(spec, part)), base]
    if (parts.some((part) => part.oneOf || part.anyOf || (part.type && part.type !== 'object'))) {
        throw new Error('Object composition with union or scalar branches needs an SDK adapter')
    }
    const properties = {}
    for (const part of parts) {
        for (const [key, value] of Object.entries(part.properties ?? {})) {
            if (properties[key] && JSON.stringify(properties[key]) !== JSON.stringify(value)) {
                throw new Error(`Conflicting allOf property ${key} needs an SDK adapter`)
            }
            properties[key] = value
        }
    }
    return {
        ...Object.assign({}, ...parts),
        type: 'object',
        properties,
        required: [...new Set(parts.flatMap((part) => part.required ?? []))],
    }
}

/** Shape the schema with the same dotted paths that shape the runtime response. */
export function projectSchema(spec, node, paths, mode, selectable = false) {
    let schema = objectSchema(spec, node)
    if (!paths?.length) {
        return schema
    }
    if (Array.isArray(schema.type)) {
        const { type, ...rest } = schema
        schema = { anyOf: type.map((value) => ({ ...rest, type: value })) }
    }
    if (schema.anyOf || schema.oneOf) {
        const kind = schema.anyOf ? 'anyOf' : 'oneOf'
        return {
            ...schema,
            [kind]: schema[kind].map((variant) => projectSchema(spec, variant, paths, mode, selectable)),
        }
    }
    if (schema.type === 'array') {
        if (paths.some((value) => !value.startsWith('*.'))) {
            throw new Error('Array projection paths must start with *.')
        }
        return {
            ...schema,
            items: projectSchema(
                spec,
                schema.items,
                paths.map((value) => value.slice(2)),
                mode,
                selectable
            ),
        }
    }
    if (!schema.properties) {
        if (schema.type === 'null') {
            return schema
        }
        if (mode === 'exclude' && (!schema.type || schema.type === 'object')) {
            return schema
        }
        throw new Error(`Cannot project fields from an unstructured schema: ${paths.join(', ')}`)
    }
    const groups = new Map()
    for (const value of paths) {
        const [key, ...tail] = value.split('.')
        if (!(key in schema.properties)) {
            if (mode === 'exclude') {
                continue
            }
            throw new Error(`Projection field ${value} is absent from its source schema`)
        }
        if (!groups.has(key)) {
            groups.set(key, [])
        }
        groups.get(key).push(tail.join('.'))
    }
    const properties = mode === 'include' ? {} : { ...schema.properties }
    for (const [key, tails] of groups) {
        if (tails.includes('')) {
            if (mode === 'include') {
                properties[key] = schema.properties[key]
            } else {
                delete properties[key]
            }
        } else {
            properties[key] = projectSchema(spec, schema.properties[key], tails, mode, selectable)
        }
    }
    return {
        ...schema,
        properties,
        required: selectable ? [] : (schema.required ?? []).filter((key) => Object.hasOwn(properties, key)),
        ...(mode === 'include' ? { additionalProperties: false } : {}),
    }
}

const JSON_SCHEMAS = {
    JsonObject: { type: 'object', additionalProperties: { $ref: '#/components/schemas/JsonValue' } },
    JsonValue: {
        anyOf: [
            { type: 'string' },
            { type: 'number' },
            { type: 'boolean' },
            { type: 'null' },
            { $ref: '#/components/schemas/JsonObject' },
            { type: 'array', items: { $ref: '#/components/schemas/JsonValue' } },
        ],
    },
}

/** Operation-local registries prevent a projection or PATCH override changing another method's schema. */
export class SchemaRegistry {
    constructor(spec, prefix) {
        this.spec = spec
        this.prefix = prefix
        this.schemas = structuredClone(JSON_SCHEMAS)
        this.refs = new Map()
    }

    normalize(node, name, direction, { patch = false, stripNulls = false, nullOptional = false } = {}) {
        if (node === false) {
            return false
        }
        if (node === true || !node || Object.keys(node).length === 0) {
            return { $ref: '#/components/schemas/JsonValue' }
        }
        if (patch && Object.hasOwn(node, 'default')) {
            node = { ...node }
            delete node.default
        }
        if (node.nullable) {
            const { nullable, ...value } = node
            return this.normalize(
                { anyOf: [value, { type: 'null' }], ...(value.description ? { description: value.description } : {}) },
                name,
                direction,
                { patch, stripNulls, nullOptional }
            )
        }
        if (node.$ref) {
            if (
                node.$ref.startsWith('#/components/schemas/') &&
                Object.hasOwn(JSON_SCHEMAS, node.$ref.split('/').at(-1)) &&
                !this.spec.components?.schemas?.[node.$ref.split('/').at(-1)]
            ) {
                return node
            }
            const key = `${direction}:${patch}:${stripNulls}:${nullOptional}:${node.$ref}`
            let targetName = this.refs.get(key)
            if (!targetName) {
                targetName = `${this.prefix}${direction === 'input' ? 'Request' : 'Response'}${pascalCase(node.$ref.split('/').at(-1))}${stripNulls ? 'WithoutNulls' : ''}${nullOptional ? 'NullableFields' : ''}`
                this.refs.set(key, targetName)
                this.schemas[targetName] = {}
                this.schemas[targetName] = this.normalize(
                    resolveRef(this.spec, { $ref: node.$ref }),
                    targetName,
                    direction,
                    { patch, stripNulls, nullOptional }
                )
            }
            const { $ref, ...siblings } = node
            return { $ref: `#/components/schemas/${targetName}`, ...siblings }
        }
        let schema = structuredClone(objectSchema(this.spec, node))
        delete schema.$schema
        delete schema.$defs
        delete schema.definitions
        if (typeof schema.deprecated === 'string') {
            schema.description = `${schema.description ?? ''}\n\n@deprecated ${schema.deprecated}`.trim()
            schema.deprecated = true
        }
        if (Array.isArray(schema.type)) {
            const { type, ...rest } = schema
            schema = { ...rest, anyOf: type.map((value) => ({ ...rest, type: value })) }
            delete schema.properties
            delete schema.items
            delete schema.required
        }
        delete schema.discriminator
        delete schema.xml
        if (patch) {
            delete schema.default
        }
        for (const kind of ['anyOf', 'oneOf']) {
            if (schema[kind]) {
                schema[kind] = schema[kind].map((part, index) =>
                    this.normalize(part, `${name}Variant${index + 1}`, direction, { patch, stripNulls, nullOptional })
                )
            }
        }
        if (schema.properties || schema.type === 'object') {
            const properties = {}
            const removedNulls = new Set()
            for (const [key, raw] of Object.entries(schema.properties ?? {})) {
                const value = resolveRef(this.spec, raw)
                if ((direction === 'input' && value.readOnly) || (direction === 'output' && value.writeOnly)) {
                    continue
                }
                let property = raw
                if (
                    stripNulls &&
                    (value.nullable ||
                        value.type === 'null' ||
                        value.type?.includes?.('null') ||
                        [...(value.anyOf ?? []), ...(value.oneOf ?? [])].some((part) => part.type === 'null'))
                ) {
                    property = { ...value }
                    delete property.nullable
                    if (Array.isArray(property.type)) {
                        property.type = property.type.filter((type) => type !== 'null')
                    }
                    for (const kind of ['anyOf', 'oneOf']) {
                        if (property[kind]) {
                            property[kind] = property[kind].filter((part) => part.type !== 'null')
                        }
                    }
                    if (
                        property.type === 'null' ||
                        property.type?.length === 0 ||
                        property.anyOf?.length === 0 ||
                        property.oneOf?.length === 0
                    ) {
                        continue
                    }
                    removedNulls.add(key)
                }
                if (nullOptional && !stripNulls && !(schema.required ?? []).includes(key)) {
                    property = {
                        anyOf: [property, { type: 'null' }],
                        ...Object.fromEntries(
                            Object.entries(value).filter(
                                ([name]) =>
                                    name.startsWith('x-') || ['description', 'deprecated', 'readOnly'].includes(name)
                            )
                        ),
                    }
                }
                properties[key] = this.normalize(property, `${name}${pascalCase(key)}`, direction, {
                    patch,
                    stripNulls,
                    nullOptional,
                })
            }
            schema.properties = properties
            schema.type = 'object'
            schema.required = (schema.required ?? []).filter(
                (key) => Object.hasOwn(properties, key) && !removedNulls.has(key)
            )
            if (typeof schema.additionalProperties === 'object') {
                schema.additionalProperties = this.normalize(schema.additionalProperties, `${name}Value`, direction, {
                    patch,
                    stripNulls,
                    nullOptional,
                })
            }
            if (
                !Object.keys(properties).length &&
                schema.additionalProperties !== false &&
                schema.additionalProperties === undefined
            ) {
                schema.additionalProperties = { $ref: '#/components/schemas/JsonValue' }
            }
        }
        if (schema.items) {
            schema.items = this.normalize(schema.items, `${name}Item`, direction, { patch, stripNulls, nullOptional })
        }
        for (const key of ['propertyNames', 'contains', 'not', 'if', 'then', 'else', 'additionalItems']) {
            if (typeof schema[key] === 'object') {
                schema[key] = this.normalize(schema[key], `${name}${pascalCase(key)}`, direction, {
                    patch,
                    stripNulls,
                    nullOptional,
                })
            }
        }
        for (const key of ['patternProperties', 'dependentSchemas']) {
            if (schema[key]) {
                schema[key] = Object.fromEntries(
                    Object.entries(schema[key]).map(([field, value]) => [
                        field,
                        this.normalize(value, `${name}${pascalCase(field)}`, direction, {
                            patch,
                            stripNulls,
                            nullOptional,
                        }),
                    ])
                )
            }
        }
        if (schema.prefixItems) {
            schema.prefixItems = schema.prefixItems.map((value, index) =>
                this.normalize(value, `${name}Item${index + 1}`, direction, { patch, stripNulls, nullOptional })
            )
        }
        if (!schema.type && !schema.anyOf && !schema.oneOf && !schema.enum && !Object.hasOwn(schema, 'const')) {
            return { $ref: '#/components/schemas/JsonValue', ...schema }
        }
        return schema
    }

    add(name, schema, direction, options) {
        this.schemas[name] = this.normalize(objectSchema(this.spec, schema), name, direction, options)
        return { $ref: `#/components/schemas/${name}` }
    }
}
