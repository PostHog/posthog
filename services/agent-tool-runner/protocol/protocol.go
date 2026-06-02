// Package protocol defines the JSON wire shapes the runner exchanges with
// the PostHog ingress. Every type here corresponds to a documented endpoint
// in docs/agent-platform/plans/self-hosted-tool-runners.md.
//
// This package has zero behaviour — it only declares the contract. Both the
// runner and (eventually) PostHog ingress encode/decode against these types.
package protocol

import "encoding/json"

// HeartbeatRequest is sent on register and at the configured heartbeat
// interval. Body of POST /runners/heartbeat. Replaces the runner's tool
// catalog wholesale on each call.
type HeartbeatRequest struct {
	// Opaque, runner-instance UUID. Re-generated on process boot. Used by
	// the ingress to attribute leases to a specific running process for
	// HA-debug purposes; not used for auth.
	InstanceID string `json:"instance_id"`

	// Free-form version label the runner reports (image tag, git sha).
	// Surfaced in the PostHog UI; no behaviour depends on it.
	Version string `json:"version,omitempty"`

	// Tool catalog this runner exposes for the project this token belongs
	// to. Replaces tool_runner_tool rows wholesale.
	Tools []ToolDescriptor `json:"tools"`
}

// ToolDescriptor mirrors the MCP `Tool` shape — name, description, JSON
// Schema for inputs. PostHog stores this verbatim and serves it back to
// agent freeze-time validation.
type ToolDescriptor struct {
	Name        string          `json:"name"`
	Description string          `json:"description,omitempty"`
	InputSchema json.RawMessage `json:"input_schema"`
}

// HeartbeatResponse acknowledges a heartbeat. Currently empty; reserved
// for future server-driven directives (rotate token, drain, etc.).
type HeartbeatResponse struct{}

// PollResponse is what GET /runners/poll returns. If no invocation became
// available within the long-poll window the server returns 204 with no
// body; the runner re-polls immediately.
type PollResponse struct {
	Invocation *LeasedInvocation `json:"invocation"`
}

// LeasedInvocation is one piece of work the ingress has assigned to this
// runner. The runner must POST a result before LeaseExpiresAt or call
// extend_lease to push it out.
type LeasedInvocation struct {
	ID                string          `json:"id"`
	ToolName          string          `json:"tool_name"`
	Args              json.RawMessage `json:"args"`
	LeaseExpiresAtISO string          `json:"lease_expires_at"`
	// Optional context echoed back for log correlation. The runner does
	// not interpret these — they exist so the runner-side log line matches
	// the agent-side log line on the PostHog side.
	SessionID string `json:"session_id,omitempty"`
	TurnID    string `json:"turn_id,omitempty"`
}

// ResultRequest is the body of POST /runners/invocations/:id/result.
// Exactly one of Result / Error is non-empty.
type ResultRequest struct {
	Status string          `json:"status"` // "done" | "failed"
	Result json.RawMessage `json:"result,omitempty"`
	Error  string          `json:"error,omitempty"`
}

// ExtendLeaseRequest is the body of POST /runners/invocations/:id/extend_lease.
type ExtendLeaseRequest struct {
	// How long from now the new lease should run. The ingress may clamp
	// this to a server-side maximum; the response carries the actual value.
	ExtendBySeconds int `json:"extend_by_seconds"`
}

// ExtendLeaseResponse echoes the lease's new expiry.
type ExtendLeaseResponse struct {
	LeaseExpiresAtISO string `json:"lease_expires_at"`
}

// ErrorResponse is the standard envelope for non-2xx responses from the
// ingress. Runners log .Code for telemetry and surface .Message into
// their own logs.
type ErrorResponse struct {
	Code    string `json:"code"`
	Message string `json:"message"`
}
