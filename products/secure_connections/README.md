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

## Integration path

Connections are identified by the UUID returned by the control plane.
Future data warehouse sources, CDP destinations, and MCP server installations can store this UUID as a soft reference on their existing team-owned configuration.
At execution time, trusted workers should exchange the team ID and connection UUID for a short-lived local forwarder while keeping the integration's existing application credentials and TLS configuration.
Workers must fail closed if the forwarder cannot be created.
