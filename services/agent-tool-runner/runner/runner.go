// Package runner is the per-project orchestration loop. One Runner is
// constructed per ProjectConfig and owns:
//
//   - one heartbeat ticker, replacing the catalog wholesale on each tick
//   - one long-poll worker, leasing invocations
//   - a dispatch step that hands the invocation to the appropriate Source
//   - posting the result (or error) back to PostHog
//
// Goroutines live for the lifetime of ctx. Cancelling ctx drains in-flight
// invocations (best-effort within a configurable shutdown grace).
package runner

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"log/slog"
	"sync"
	"sync/atomic"
	"time"

	"github.com/posthog/posthog/services/agent-tool-runner/client"
	"github.com/posthog/posthog/services/agent-tool-runner/protocol"
)

// Source is what the runner dispatches to. The reference runner ships two
// impls (MCP proxy, shell command), but any Source that satisfies this
// interface plugs in. Custom runners can provide their own.
type Source interface {
	// Tools returns the catalog this source contributes. The runner
	// concatenates all sources' tools on each heartbeat. Names must be
	// `<source>.<tool>` qualified — the heartbeat catalog uses these
	// qualified names so PostHog can attribute calls to a source for
	// debug purposes (the spec author's tool list uses the same form).
	Tools() []protocol.ToolDescriptor

	// Call executes one invocation. Returns the JSON-encoded result on
	// success or an error. Sources MUST honour ctx.Done() — the runner
	// uses ctx to enforce lease deadlines and shutdown.
	Call(ctx context.Context, toolName string, args json.RawMessage) (json.RawMessage, error)

	// Close releases any resources the Source holds (open MCP clients,
	// subprocesses). The runner does NOT call this — sources are usually
	// shared across multiple project loops, so close responsibility
	// belongs to the process owner (main.go). Safe to call multiple times.
	Close() error
}

// Options configures one project runner loop.
type Options struct {
	// Version label reported in heartbeats (image tag or git sha).
	Version string

	// Tool sources active for this runner. Only the qualified names listed
	// in `Expose` will be advertised in heartbeats — the runner filters
	// the union of `Tools()` from every Source against this list.
	Sources []Source

	// Tool names from `Sources` to advertise to PostHog for this project.
	// Names are `<source>.<tool>` qualified.
	Expose []string

	// Ingress client. Single-token, single-endpoint — one per Runner.
	Client *client.Client

	// HeartbeatInterval governs the cadence of heartbeats once registered.
	// Default: 30s. The ingress flips status to `stale` after 5m without
	// a heartbeat, so anything below ~2m is fine.
	HeartbeatInterval time.Duration

	// PollMaxWait is forwarded to the ingress as the long-poll window
	// hint. Default: 30s.
	PollMaxWait time.Duration

	// LeaseExtensionFor controls how long each `extend_lease` call asks
	// for. Default: 60s. The runner sends an extension request at half
	// this interval so a single missed RPC still leaves headroom before
	// the current lease expires.
	LeaseExtensionFor time.Duration

	// RegisterBackoffMin / RegisterBackoffMax bound the exponential
	// backoff used while retrying the initial registration. The runner
	// keeps retrying until ctx is cancelled — it never exits the process
	// just because PostHog is unreachable at boot. Defaults: 1s / 30s.
	RegisterBackoffMin time.Duration
	RegisterBackoffMax time.Duration

	// DegradedAfter is how many consecutive heartbeat failures (after a
	// successful registration) transition the runner from `live` to
	// `degraded`. Default: 3. The health-check endpoint reports
	// `degraded` runners as unhealthy.
	DegradedAfter int

	// Logger receives one log line per significant event (register,
	// lease, complete, error). Optional — if nil, slog.Default() is used.
	Logger *slog.Logger
}

// State is a runner's lifecycle position, surfaced via State() for the
// health-check endpoint. Transitions:
//
//	connecting → live   (first successful heartbeat)
//	live       → degraded (DegradedAfter consecutive heartbeat failures)
//	degraded   → live   (any successful heartbeat)
//
// `connecting` is sticky — until the first heartbeat succeeds, the runner
// stays in this state regardless of how many retries have failed.
type State string

const (
	StateConnecting State = "connecting"
	StateLive       State = "live"
	StateDegraded   State = "degraded"
)

// Runner is one project's loop. Construct via New, drive via Run.
type Runner struct {
	opts         Options
	instanceID   string
	logger       *slog.Logger
	catalog      []protocol.ToolDescriptor // computed once at construction
	toolToSource map[string]Source         // qualified name -> impl
	inFlightWG   sync.WaitGroup            // tracks in-flight invocations for graceful shutdown

	state                   atomic.Value // State
	consecutiveHeartbeatErr atomic.Int32
}

// New validates options and prepares the cached tool catalog. It does not
// perform any network IO.
func New(opts Options) (*Runner, error) {
	if opts.Client == nil {
		return nil, errors.New("runner: Client is required")
	}
	if len(opts.Sources) == 0 {
		return nil, errors.New("runner: at least one Source is required")
	}
	if len(opts.Expose) == 0 {
		return nil, errors.New("runner: Expose must list at least one tool")
	}
	if opts.HeartbeatInterval == 0 {
		opts.HeartbeatInterval = 30 * time.Second
	}
	if opts.PollMaxWait == 0 {
		opts.PollMaxWait = 30 * time.Second
	}
	if opts.LeaseExtensionFor == 0 {
		opts.LeaseExtensionFor = 60 * time.Second
	}
	if opts.RegisterBackoffMin == 0 {
		opts.RegisterBackoffMin = 1 * time.Second
	}
	if opts.RegisterBackoffMax == 0 {
		opts.RegisterBackoffMax = 30 * time.Second
	}
	if opts.DegradedAfter == 0 {
		opts.DegradedAfter = 3
	}
	logger := opts.Logger
	if logger == nil {
		logger = slog.Default()
	}

	// Build qualified-name -> Source map and the published catalog.
	toolToSource := make(map[string]Source)
	for _, s := range opts.Sources {
		for _, tool := range s.Tools() {
			if _, exists := toolToSource[tool.Name]; exists {
				return nil, fmt.Errorf("runner: duplicate tool name %q across sources", tool.Name)
			}
			toolToSource[tool.Name] = s
		}
	}
	exposed := make([]protocol.ToolDescriptor, 0, len(opts.Expose))
	for _, name := range opts.Expose {
		src, ok := toolToSource[name]
		if !ok {
			return nil, fmt.Errorf("runner: exposed tool %q is not provided by any source", name)
		}
		for _, tool := range src.Tools() {
			if tool.Name == name {
				exposed = append(exposed, tool)
				break
			}
		}
	}

	r := &Runner{
		opts:         opts,
		instanceID:   newInstanceID(),
		logger:       logger,
		catalog:      exposed,
		toolToSource: toolToSource,
	}
	r.state.Store(StateConnecting)
	return r, nil
}

// State returns the runner's current lifecycle state. Safe to call from
// any goroutine — used by the health-check endpoint in main.
func (r *Runner) State() State {
	v := r.state.Load()
	if v == nil {
		return StateConnecting
	}
	return v.(State)
}

func (r *Runner) setState(s State) { r.state.Store(s) }

// newInstanceID returns a random 128-bit identifier as a hex string. Used
// purely for log attribution on the PostHog side; not security-sensitive.
func newInstanceID() string {
	var b [16]byte
	if _, err := rand.Read(b[:]); err != nil {
		// crypto/rand should never fail on a healthy host. If it does we
		// have bigger problems than instance-id uniqueness.
		panic(fmt.Sprintf("crypto/rand: %v", err))
	}
	return hex.EncodeToString(b[:])
}

// Run blocks until ctx is cancelled. It runs three concurrent goroutines:
// the heartbeat loop, the poll loop, and a wait for graceful drain.
//
// **Resilience policy:** Run does NOT return on transient PostHog-side
// failures. The initial registration retries with exponential backoff
// indefinitely (until ctx is cancelled). Once registered, heartbeat
// failures decrement the runner's health state but the loop keeps
// running. The only error path Run returns is ctx.Done().
func (r *Runner) Run(ctx context.Context) error {
	if err := r.registerWithBackoff(ctx); err != nil {
		// Only reached if ctx was cancelled before the first heartbeat
		// ever succeeded.
		return err
	}
	r.setState(StateLive)
	r.logger.Info("registered with PostHog ingress",
		slog.String("instance_id", r.instanceID),
		slog.Int("catalog_size", len(r.catalog)))

	errCh := make(chan error, 2)
	var wg sync.WaitGroup
	wg.Add(2)

	go func() {
		defer wg.Done()
		errCh <- r.heartbeatLoop(ctx)
	}()
	go func() {
		defer wg.Done()
		errCh <- r.pollLoop(ctx)
	}()

	wg.Wait()
	close(errCh)

	// Drain in-flight invocations. They each have their own deadline via
	// the lease; we just need them to finish posting results before exit.
	r.inFlightWG.Wait()

	for err := range errCh {
		if err != nil && !errors.Is(err, context.Canceled) {
			return err
		}
	}
	return nil
}

// registerWithBackoff calls heartbeat() until it succeeds or ctx is
// cancelled. The first call is immediate; subsequent retries use
// exponential backoff capped at RegisterBackoffMax. The state stays
// `connecting` for the entire duration; the health endpoint reports
// "unhealthy" until this returns nil.
func (r *Runner) registerWithBackoff(ctx context.Context) error {
	backoff := r.opts.RegisterBackoffMin
	for {
		err := r.heartbeat(ctx)
		if err == nil {
			return nil
		}
		if errors.Is(err, context.Canceled) {
			return err
		}
		r.logger.Warn("initial register failed; will retry",
			slog.Duration("backoff", backoff),
			slog.String("err", err.Error()))
		select {
		case <-ctx.Done():
			return ctx.Err()
		case <-time.After(backoff):
		}
		backoff = nextBackoff(backoff, r.opts.RegisterBackoffMax)
	}
}

// nextBackoff doubles the current backoff, capped at max.
func nextBackoff(current, max time.Duration) time.Duration {
	next := current * 2
	if next > max {
		return max
	}
	return next
}

func (r *Runner) heartbeatLoop(ctx context.Context) error {
	ticker := time.NewTicker(r.opts.HeartbeatInterval)
	defer ticker.Stop()
	for {
		select {
		case <-ctx.Done():
			return ctx.Err()
		case <-ticker.C:
			if err := r.heartbeat(ctx); err != nil {
				failures := r.consecutiveHeartbeatErr.Add(1)
				r.logger.Warn("heartbeat failed; will retry next tick",
					slog.Int("consecutive_failures", int(failures)),
					slog.String("err", err.Error()))
				if int(failures) >= r.opts.DegradedAfter && r.State() == StateLive {
					r.setState(StateDegraded)
					r.logger.Warn("runner degraded — heartbeats failing",
						slog.Int("consecutive_failures", int(failures)))
				}
				continue
			}
			r.consecutiveHeartbeatErr.Store(0)
			if r.State() != StateLive {
				r.setState(StateLive)
				r.logger.Info("runner back to live")
			}
		}
	}
}

func (r *Runner) heartbeat(ctx context.Context) error {
	_, err := r.opts.Client.Heartbeat(ctx, protocol.HeartbeatRequest{
		InstanceID: r.instanceID,
		Version:    r.opts.Version,
		Tools:      r.catalog,
	})
	return err
}

func (r *Runner) pollLoop(ctx context.Context) error {
	for {
		if ctx.Err() != nil {
			return ctx.Err()
		}
		inv, err := r.opts.Client.Poll(ctx, r.opts.PollMaxWait)
		if err != nil {
			if errors.Is(err, context.Canceled) {
				return err
			}
			// Transient — backoff briefly and retry. The ingress will
			// re-lease anything we leased-but-didn't-complete after the
			// lease expires.
			r.logger.Warn("poll failed; backing off",
				slog.String("err", err.Error()))
			select {
			case <-ctx.Done():
				return ctx.Err()
			case <-time.After(2 * time.Second):
			}
			continue
		}
		if inv == nil {
			continue // 204, no work, immediate re-poll
		}
		r.inFlightWG.Add(1)
		go func(inv *protocol.LeasedInvocation) {
			defer r.inFlightWG.Done()
			r.dispatch(ctx, inv)
		}(inv)
	}
}

func (r *Runner) dispatch(ctx context.Context, inv *protocol.LeasedInvocation) {
	logger := r.logger.With(
		slog.String("invocation_id", inv.ID),
		slog.String("tool_name", inv.ToolName),
		slog.String("session_id", inv.SessionID),
	)
	logger.Info("leased invocation")

	source, ok := r.toolToSource[inv.ToolName]
	if !ok {
		// PostHog leased us something we don't serve — never expected to
		// happen since we publish the catalog, but report a clear error
		// rather than silently dropping the lease.
		r.reportError(ctx, inv.ID, fmt.Errorf("tool %q not served by this runner", inv.ToolName))
		logger.Error("rejected unknown tool — runner & ingress catalogs out of sync")
		return
	}

	leaseDeadline, ok := parseISOTime(inv.LeaseExpiresAtISO)
	if !ok {
		r.reportError(ctx, inv.ID, fmt.Errorf("invalid lease_expires_at %q", inv.LeaseExpiresAtISO))
		return
	}

	// Tool execution runs under a context whose deadline is the *current*
	// lease deadline. The lease-extension goroutine pushes the deadline
	// out as long as the tool is still running, so long-running tools
	// (e.g. waiting on a k8s rollout) don't get cut off.
	callCtx, cancel := context.WithCancel(ctx)
	defer cancel()
	leaseCtx, stopLeaseExt := context.WithCancel(ctx)
	go r.extendLeaseLoop(leaseCtx, inv.ID, leaseDeadline, logger)

	result, err := source.Call(callCtx, inv.ToolName, inv.Args)
	stopLeaseExt()
	if err != nil {
		r.reportError(ctx, inv.ID, err)
		logger.Warn("tool call failed", slog.String("err", err.Error()))
		return
	}
	if err := r.opts.Client.PostResult(ctx, inv.ID, protocol.ResultRequest{
		Status: "done",
		Result: result,
	}); err != nil {
		// At this point the work is done locally but we couldn't tell
		// PostHog. The lease will expire and the invocation will be
		// re-leased; sources need to be idempotent OR wrapped in
		// approval gates — both already required by the platform.
		logger.Warn("posting result failed; lease will expire and invocation re-queue",
			slog.String("err", err.Error()))
		return
	}
	logger.Info("invocation done")
}

// extendLeaseLoop keeps pushing the lease deadline out while the tool is
// still executing. Exits cleanly when ctx is cancelled (which happens
// when source.Call returns). Errors are logged but not fatal — the next
// successful extension will recover. If extensions repeatedly fail and
// the original lease elapses, PostHog re-queues the invocation; the work
// completes locally either way.
func (r *Runner) extendLeaseLoop(ctx context.Context, invocationID string, initialDeadline time.Time, logger *slog.Logger) {
	// Send the first extension at half the lease window. Subsequent
	// extensions follow the same cadence relative to the new lease.
	currentDeadline := initialDeadline
	for {
		// Sleep until halfway between now and the current deadline.
		half := time.Until(currentDeadline) / 2
		if half <= 0 {
			// We've already crossed the deadline — either the initial
			// lease was tight or extensions have been failing. Nothing
			// to do; let source.Call's context-deadline take over.
			return
		}
		select {
		case <-ctx.Done():
			return
		case <-time.After(half):
		}

		resp, err := r.opts.Client.ExtendLease(ctx, invocationID, protocol.ExtendLeaseRequest{
			ExtendBySeconds: int(r.opts.LeaseExtensionFor / time.Second),
		})
		if err != nil {
			if errors.Is(err, context.Canceled) {
				return // dispatch finished while we were mid-call; not an error
			}
			logger.Warn("extend_lease failed; tool will continue but invocation may re-queue",
				slog.String("err", err.Error()))
			continue
		}
		newDeadline, ok := parseISOTime(resp.LeaseExpiresAtISO)
		if !ok {
			logger.Warn("extend_lease returned malformed lease_expires_at",
				slog.String("value", resp.LeaseExpiresAtISO))
			continue
		}
		currentDeadline = newDeadline
	}
}

func (r *Runner) reportError(ctx context.Context, invocationID string, err error) {
	postErr := r.opts.Client.PostResult(ctx, invocationID, protocol.ResultRequest{
		Status: "failed",
		Error:  err.Error(),
	})
	if postErr != nil {
		r.logger.Warn("posting failure result failed",
			slog.String("invocation_id", invocationID),
			slog.String("err", postErr.Error()))
	}
}

func parseISOTime(s string) (time.Time, bool) {
	t, err := time.Parse(time.RFC3339Nano, s)
	if err != nil {
		t, err = time.Parse(time.RFC3339, s)
		if err != nil {
			return time.Time{}, false
		}
	}
	return t, true
}
