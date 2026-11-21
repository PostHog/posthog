function transform(value, reference) {
    if (Array.isArray(value)) {
        return value.map((item) => transform(item, reference))
    }
    if (!value || typeof value !== 'object') {
        return value
    }
    return Object.fromEntries(
        Object.entries(value).map(([key, child]) => [
            key,
            key === '$ref' ? reference(child.split('/').at(-1)) : transform(child, reference),
        ])
    )
}

export class SdkTypeRegistry {
    constructor(operations) {
        this.entries = new Map()
        for (const operation of operations) {
            const references = new Map([...operation.registry.refs].map(([key, name]) => [name, key]))
            for (const [name, schema] of Object.entries(operation.registry.schemas)) {
                const identity = references.get(name) ?? name
                const existing = this.entries.get(name)
                if (existing && JSON.stringify(existing.schema) !== JSON.stringify(schema)) {
                    throw new Error(`Conflicting SDK type ${name}`)
                }
                this.entries.set(name, { identity, schema })
            }
        }
    }

    merge() {
        let groups = new Map()
        const identities = new Map()
        for (const [name, { identity }] of this.entries) {
            if (!identities.has(identity)) {
                identities.set(identity, identities.size)
            }
            groups.set(name, identities.get(identity))
        }
        // Equivalent parents can share a type only when their entire referenced graph agrees, including cycles and documentation.
        for (;;) {
            const signatures = new Map()
            const refined = new Map()
            for (const [name, { schema }] of this.entries) {
                const signature = JSON.stringify([groups.get(name), transform(schema, (target) => groups.get(target))])
                if (!signatures.has(signature)) {
                    signatures.set(signature, signatures.size)
                }
                refined.set(name, signatures.get(signature))
            }
            const count = new Set(groups.values()).size
            groups = refined
            if (signatures.size === count) {
                break
            }
        }
        const canonical = new Map()
        for (const [name, group] of groups) {
            if (!canonical.has(group)) {
                canonical.set(group, name)
            }
        }
        const names = new Map([...groups].map(([name, group]) => [name, canonical.get(group)]))
        const schemas = {}
        for (const [name, { schema }] of this.entries) {
            if (names.get(name) === name) {
                schemas[name] = transform(schema, (target) => {
                    if (!names.has(target)) {
                        throw new Error(`Missing SDK type ${target}`)
                    }
                    return `#/components/schemas/${names.get(target)}`
                })
            }
        }
        return { schemas, aliases: new Map([...names].filter(([name, target]) => name !== target)) }
    }
}
