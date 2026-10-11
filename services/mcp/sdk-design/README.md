# TypeScript SDK for PostHog agents

The implementation lives in [packages/sdk](../../../packages/sdk/README.md) and is published under the package name `@posthog/sdk`.
It exports a default and named `client`, plus `createPostHogClient` for explicit configuration.
Calls go directly to the PostHog HTTP API with a personal API key, OAuth token, or authentication supplied by a Tasks proxy.

## Catalog parity

Every tool registered in MCP has a corresponding SDK method.
This includes REST tools, query wrappers in both standalone and product YAML files, handwritten handlers, deprecated aliases, and separate prepare/execute tools.
Disabled MCP definitions belong to neither catalog.

[generate-sdk.mjs](../scripts/generate-sdk.mjs) compares the combined MCP factory registry against `tool-definitions-all.json` before generation.
It emits `coverage.json` as a complete mapping from MCP names to SDK method names.
The SDK tests compare these sets again, so adding a tool to MCP without regenerating the SDK fails validation.

YAML entries may specify `sdk: { namespace, method }` to customize naming.
This is a naming override, not an inclusion flag.
The default namespace is the definition's module; the default method is the camel-cased MCP tool name.
Duplicate method names fail generation.

## Contracts and documentation

The package ships TypeScript source and declarations containing explicit interfaces for object inputs, outputs, and nested objects.
Union inputs refer to named interface variants.
Agents can follow the types with grep without resolving `z.infer`, `ReturnType`, or generic type assertions.

Input contracts come from the actual MCP validators, including custom schemas, aliases, and overrides.
The generator reads factory result types before the registry erases their generics, supplements them with OpenAPI and query schemas, and applies response projections.
Known hook additions and alternate results have explicit contracts.
The structured SQL and analytics adapters expose completed, pending, and failed query outcomes.

The generated files preserve original schema comments and effective overrides.
Method JSDoc contains complete tool descriptions, original descriptions, scope requirements, and MCP names.
The single `src/generated/api.ts` registry retains full method JSDoc and schema comments; the TSV indexes point to its named contracts.
Open JSON fields and source schema gaps remain documented `JsonValue` contracts; the generator does not invent result fields.

## Shared execution

[sdk/host.ts](../sdk/host.ts) runs the same generated and handwritten handlers as MCP.
The package bundles these handlers with an SDK host; it does not require an MCP connection, a running MCP server, Redis, or Cloudflare.
Hooks, validators, request shaping, response projections, trace redaction, and multi-step workflows therefore use the shared implementation.

The host supplies direct HTTP transport, client-local state, deadlines, and task context.
Token mode sets the bearer token; proxy mode omits it and preserves the proxy's route prefix.
Public links use the configured public PostHog URL.
The API authorizes each request, and AI-consuming methods check the target organization's processing consent before execution.
Availability metadata remains discoverable even when a credential cannot call a method.

The SDK retains independent project clients through `client.project(id)`.
Context switching tools affect only their client instance and cannot change an immutable project scope.
Default project resolution uses explicit options, environment values, or permitted token/user context.

Confirmed actions use the shared signing and verification code with a client-local, expiring store.
Tokens remain bound to the action, caller instance, and scope, and are consumed once before execution.
Prepare and execute must use the same client instance in the same process.
Backend confirmation tokens, such as workflow audience confirmations, still travel to and are checked by the backend.

Task comment and artifact tools use `taskId` or `POSTHOG_TASK_ID`.
The `agent-feedback` tool requires a configured feedback callback because the SDK host owns its feedback sink.
UI tools return structured payloads without opening an MCP UI renderer.
Tool error envelopes become rejected SDK promises rather than successful data.

## Offline discovery

After installation, run `npx @posthog/sdk --agent-help` to read the workflow guide, available domains, and absolute local paths to the registry and indexes.
Search `api-index.tsv` with grep or rg to select a method, then read its JSDoc and named input/output interfaces in `src/generated/api.ts`.
Follow referenced type names with bounded searches; shared type graphs are deduplicated only when their shapes and documentation agree.
`domains.tsv` lists each domain's method count and import path.

These files and the guide work offline without credentials.
`@posthog/sdk/discovery` exposes static `operations` and `domains` arrays for ordinary JavaScript filtering.
Agents can save parameterized scripts in their own skills or scratchpads for repeated work, keeping credentials in the environment and output compact.

## Generation and validation

`hogli build:openapi` generates the backend schema and MCP artifacts before running `build:openapi-sdk`.
SDK generation reads OpenAPI, query schemas, MCP definitions, and the shared handler source.
It writes into a staging directory and replaces artifacts only after generation succeeds.

Validation covers catalog parity, source/declaration interfaces, documentation preservation, authentication, context resolution, shared hooks, confirmations, query behavior, errors, and cancellation.
The package check installs a tarball in a separate project, exercises offline discovery and a mocked API call, and compiles a strict TypeScript consumer.
Publishing remains a separate release step.

The adjacent handwritten TypeScript files are early contract sketches.
Use the package's generated registry and TSV indexes for the current API surface.
