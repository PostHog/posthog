import ts from 'typescript'

export interface ReadResult {
    kind: 'operation' | 'type'
    name: string
    source: string
}

/**
 * Reads sdk.d.ts and returns the requested symbol's declaration plus one level of
 * directly-referenced types (Schemas.* references inside the primary symbol's body).
 *
 * For the prototype:
 *   - `read({ kind: 'operation', name: 'projectsList' })` returns the method signature
 *     from the `Client` interface, plus the matching Input interface and the response
 *     type (and one level of types those reference).
 *   - `read({ kind: 'type', name: 'Project' })` returns the type's declaration plus
 *     one level of refs.
 */
export class TypeReader {
    private readonly source: string
    private readonly sourceFile: ts.SourceFile
    private readonly topLevelDeclarations: Map<string, ts.Node> = new Map()
    private readonly schemasNamespaceMembers: Map<string, ts.Node> = new Map()

    constructor(sdkDtsSource: string) {
        this.source = sdkDtsSource
        this.sourceFile = ts.createSourceFile('sdk.d.ts', sdkDtsSource, ts.ScriptTarget.Latest, true)
        this.indexDeclarations()
    }

    read(kind: 'operation' | 'type', name: string): ReadResult | null {
        if (kind === 'type') {
            const node = this.schemasNamespaceMembers.get(name)
            if (!node) {
                return null
            }
            const primary = this.printNode(node)
            const referenced = this.collectReferencedTypes(node, new Set([name]))
            const inlined = referenced
                .filter((n) => n !== name)
                .map((refName) => {
                    const refNode = this.schemasNamespaceMembers.get(refName)
                    return refNode ? this.printNode(refNode) : null
                })
                .filter((s): s is string => s !== null)
            const sections = [primary, ...inlined]
            return { kind: 'type', name, source: sections.join('\n\n') }
        }

        return this.readOperation(name)
    }

    private readOperation(methodName: string): ReadResult | null {
        const clientInterface = this.topLevelDeclarations.get('Client')
        if (!clientInterface || !ts.isInterfaceDeclaration(clientInterface)) {
            return null
        }
        const method = clientInterface.members.find(
            (m) => ts.isMethodSignature(m) && m.name && ts.isIdentifier(m.name) && m.name.text === methodName
        )
        if (!method) {
            return null
        }

        const sections: string[] = [this.printNode(method)]

        const referencedTypes = new Set<string>()
        this.collectIdentifiersFromNode(method, referencedTypes)

        // Look up the input interface (e.g. ProjectsListInput) which lives at the top level.
        const inputCandidates: ts.Node[] = []
        for (const refName of referencedTypes) {
            const inputNode = this.topLevelDeclarations.get(refName)
            if (inputNode && refName !== 'Client') {
                inputCandidates.push(inputNode)
                this.collectReferencedTypes(inputNode, new Set([refName])).forEach((n) => referencedTypes.add(n))
            }
        }

        for (const inputNode of inputCandidates) {
            sections.push(this.printNode(inputNode))
        }

        for (const refName of referencedTypes) {
            const schemaNode = this.schemasNamespaceMembers.get(refName)
            if (schemaNode) {
                sections.push(this.printNode(schemaNode))
            }
        }

        return { kind: 'operation', name: methodName, source: sections.join('\n\n') }
    }

    private indexDeclarations(): void {
        for (const stmt of this.sourceFile.statements) {
            if (
                ts.isModuleDeclaration(stmt) &&
                stmt.name &&
                ts.isIdentifier(stmt.name) &&
                stmt.name.text === 'Schemas'
            ) {
                this.indexNamespace(stmt)
                continue
            }
            const name = this.getDeclarationName(stmt)
            if (name) {
                this.topLevelDeclarations.set(name, stmt)
            }
        }
    }

    private indexNamespace(ns: ts.ModuleDeclaration): void {
        if (!ns.body || !ts.isModuleBlock(ns.body)) {
            return
        }
        for (const stmt of ns.body.statements) {
            const name = this.getDeclarationName(stmt)
            if (name) {
                this.schemasNamespaceMembers.set(name, stmt)
            }
        }
    }

    private getDeclarationName(node: ts.Node): string | undefined {
        if (
            ts.isInterfaceDeclaration(node) ||
            ts.isTypeAliasDeclaration(node) ||
            ts.isClassDeclaration(node) ||
            ts.isEnumDeclaration(node)
        ) {
            return node.name?.text
        }
        if (ts.isVariableStatement(node)) {
            const decl = node.declarationList.declarations[0]
            if (decl && ts.isIdentifier(decl.name)) {
                return decl.name.text
            }
        }
        return undefined
    }

    private collectReferencedTypes(node: ts.Node, alreadySeen: Set<string>): string[] {
        const refs = new Set<string>()
        this.collectIdentifiersFromNode(node, refs)
        const filtered: string[] = []
        for (const r of refs) {
            if (alreadySeen.has(r)) {
                continue
            }
            if (this.schemasNamespaceMembers.has(r) || this.topLevelDeclarations.has(r)) {
                filtered.push(r)
            }
        }
        return filtered
    }

    private collectIdentifiersFromNode(node: ts.Node, into: Set<string>): void {
        const visit = (n: ts.Node): void => {
            if (ts.isTypeReferenceNode(n)) {
                const typeName = n.typeName
                if (ts.isIdentifier(typeName)) {
                    into.add(typeName.text)
                } else if (ts.isQualifiedName(typeName)) {
                    // Schemas.Foo → take the rightmost identifier
                    let cur: ts.QualifiedName | ts.Identifier = typeName
                    while (ts.isQualifiedName(cur)) {
                        cur = cur.right
                    }
                    if (ts.isIdentifier(cur)) {
                        into.add(cur.text)
                    }
                }
            }
            ts.forEachChild(n, visit)
        }
        ts.forEachChild(node, visit)
    }

    private printNode(node: ts.Node): string {
        const printer = ts.createPrinter({ newLine: ts.NewLineKind.LineFeed })
        return printer.printNode(ts.EmitHint.Unspecified, node, this.sourceFile)
    }
}
