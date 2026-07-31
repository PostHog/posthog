# Secure connections

Secure connections let PostHog reach explicitly allowed services on a private network without requiring inbound access.

The first slice provides an unlinked, feature-flagged setup page at `/settings/project/secure-connections`.
The Django backend derives the remote tenant from the authenticated PostHog team, provisions tenant-scoped credentials, and returns enrollment credentials only in the provisioning response.
The operator credential stays in trusted PostHog infrastructure.

## Configuration

Set these values on the PostHog web deployment:

| Setting                                | Purpose                                                    |
| -------------------------------------- | ---------------------------------------------------------- |
| `SECURE_CONNECTION_MANAGEMENT_URL`     | Internal URL for tenant and credential management.         |
| `SECURE_CONNECTION_CONTROL_URL`        | Internal URL used to read tenant-scoped connection status. |
| `SECURE_CONNECTION_PUBLIC_CONTROL_URL` | Public control URL given to the customer-side proxy.       |
| `SECURE_CONNECTION_ADMIN_TOKEN`        | Operator credential used only by the Django backend.       |

Enable the `secure-connections` feature flag for projects that should access the page.

## Local demo

Clone `PostHog/burrow` next to this repository, then run:

```bash
hogli dev:setup
hogli start
```

Choose **Secure connections** during setup.
The normal local stack then includes a `secure-connections-demo` process that starts the sibling repository's full demo and adds a managed block to `.env.local`.
Once PostHog has started, open `/settings/project/secure-connections`.
The page uses the demo's preloaded Acme tenant, lists its HTTP and Postgres services, and returns a successful connection check.

You can also start the demo without changing your saved development setup:

```bash
hogli secure-connections:demo
```

Use these commands while iterating:

```bash
hogli secure-connections:demo test
hogli secure-connections:demo env
hogli secure-connections:demo stop
```

Set `BURROW_REPO` or pass `--burrow-path` if the repositories are not siblings.

## Integration path

Connections are identified by the UUID returned by the control plane.
Future data warehouse sources, CDP destinations, and MCP server installations can store this UUID as a soft reference on their existing team-owned configuration.
At execution time, trusted workers should exchange the team ID and connection UUID for a short-lived local forwarder while keeping the integration's existing application credentials and TLS configuration.
Workers must fail closed if the forwarder cannot be created.

## CDP authorization and magic hostnames

Project admins explicitly approve individual hostname-routed services for CDP on the Secure connections page.
Approvals are denied by default and stored under `secure_connections.cdp_approved_connections` in the project's
team settings. Updates lock the team row so concurrent admin changes cannot overwrite one another.

An approved service can be addressed from destination Hog code with its stable magic hostname:

```text
<connection-uuid>.secure-connections.internal
```

The CDP worker recognizes this suffix, checks the project-scoped approval directly in Postgres, and mints a
short-lived workload grant bound to the project, connection, and `cdp-cyclotron-worker` subject. It then asks the
Burrow worker for an authenticated TCP tunnel using this contract:

```http
CONNECT /v1/connections/<connection-uuid>
Authorization: Bearer <workload-grant>
```

After the `200 Connection Established` response, HTTP bytes travel through the raw TCP stream. The worker preserves
the advertised hostname in the HTTP `Host` header. Application credentials still come from the destination
configuration. Missing approval, revoked approval, worker rejection, and transport failure all fail closed; CDP never
falls back to a direct request.

This first CDP slice supports hostname-routed HTTP services. End-to-end HTTPS requires a port-routed Connection plus
explicit TLS server-name metadata, so HTTPS magic URLs are rejected clearly instead of attempting a broken or insecure
fallback.

The PostHog integration is tested against an in-process mock of this worker contract. Burrow support for the CONNECT
endpoint is tracked separately.
