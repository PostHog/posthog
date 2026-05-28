# agent-sandbox-host

In-container Node host for the v2 Docker sandbox. Two scripts:

- `src/host.js` — long-running process. Writes `/workdir/host.alive` on boot
  so the runner-side `DockerSandbox` knows the container is ready. Idles
  after that; `docker exec` is the integration surface for dispatches.
- `src/dispatch.js` — per-invoke handler. Reads `/workdir/request.json`,
  loads `/workdir/tools/<id>/compiled.js`, runs the named action with the
  supplied args + a minimal `ctx`, writes `/workdir/response.json`.

## Building the image

```bash
cd services/agent-sandbox-host
docker build -t posthog/agent-sandbox-host:v1 .
```

`services/agent-shared-v2/src/sandbox-docker.ts` defaults to that image
tag; override with `new DockerSandboxPool({ image })` for staging tags.

## Publishing

The CI step (not yet wired) tags the build with both `:v<N>` and `:latest`
and pushes to `ghcr.io/posthog/agent-sandbox-host`. Until that exists,
local-only builds with the default tag are sufficient for dev / CI
end-to-end testing.

## Running the tests

The host package uses node's built-in `test` runner so the container image
stays dependency-free.

```bash
cd services/agent-sandbox-host
node --test src/dispatch.test.js
```

## Wire format

### Request (`/workdir/request.json`)

```json
{
  "toolId": "fetch-acme",
  "action": "default",
  "args": { "name": "world" },
  "timeoutMs": 30000
}
```

### Response (`/workdir/response.json`)

```json
{ "ok": true, "result": { "greeted": "world" } }
```

or

```json
{ "ok": false, "error": { "code": "tool_not_found", "message": "..." } }
```

### Tool contract (`/workdir/tools/<id>/compiled.js`)

```js
module.exports = {
  id: '<tool-id>',
  actions: {
    default: (args, ctx) => {
      // ctx.secrets.ref('SECRET_NAME')  → nonce string
      // ctx.log('info', 'message', { meta })
      return { ok: true }
    },
  },
}
```

`ctx.secrets.ref(name)` returns the nonce the runner-side `SecretBroker`
minted for this session. The sandbox never sees raw secret values; the
runner substitutes nonces with real values at egress.
