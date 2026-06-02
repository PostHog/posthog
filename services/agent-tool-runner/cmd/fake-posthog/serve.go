package main

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"strconv"
	"strings"
	"sync"
	"syscall"
	"time"

	"github.com/posthog/posthog/services/agent-tool-runner/protocol"
)

// serveCmd runs the dev ingress.
func serveCmd(args []string) {
	var addr string
	parseFlags("serve", args, func(fs *flag.FlagSet) {
		// :18080 avoids a default-port collision with OrbStack/Docker
		// Desktop, both of which claim :8080 on macOS.
		fs.StringVar(&addr, "addr", ":18080", "Address to bind the HTTP server to")
	})

	logger := slog.New(slog.NewTextHandler(os.Stderr, &slog.HandlerOptions{Level: slog.LevelInfo}))
	state := newServerState(logger)
	srv := &http.Server{
		Addr:              addr,
		Handler:           buildMux(state, logger),
		ReadHeaderTimeout: 5 * time.Second,
	}

	ctx, cancel := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer cancel()

	go func() {
		logger.Info("fake-posthog listening", slog.String("addr", addr))
		if err := srv.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
			logger.Error("listen failed", slog.String("err", err.Error()))
			os.Exit(1)
		}
	}()

	<-ctx.Done()
	shutCtx, shutCancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer shutCancel()
	_ = srv.Shutdown(shutCtx)
}

// serverState is the in-memory store of registered runners + their queues.
// Token is treated as an opaque runner identifier — every distinct token
// the server has seen becomes a runner row.
type serverState struct {
	mu sync.Mutex

	runners map[string]*runnerRow // keyed by bearer token (the runner's identity)

	// pending invocations awaiting a runner whose catalog contains the
	// requested tool. Once leased, an entry moves out of `pending` and
	// into `awaitingResult`.
	pending        []*pendingInvocation
	awaitingResult map[string]*pendingInvocation
	logger         *slog.Logger
}

type runnerRow struct {
	token      string // truncated for log/UI
	instanceID string
	lastHB     time.Time
	tools      []protocol.ToolDescriptor
	toolSet    map[string]struct{}
}

type pendingInvocation struct {
	id        string
	toolName  string
	args      json.RawMessage
	createdAt time.Time

	// done is closed when a result has been posted. result + err read
	// after done is closed are stable.
	done   chan struct{}
	result json.RawMessage
	err    string
}

func newServerState(logger *slog.Logger) *serverState {
	return &serverState{
		runners:        map[string]*runnerRow{},
		awaitingResult: map[string]*pendingInvocation{},
		logger:         logger,
	}
}

func buildMux(s *serverState, logger *slog.Logger) http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("/runners/heartbeat", s.handleHeartbeat)
	mux.HandleFunc("/runners/poll", s.handlePoll)
	mux.HandleFunc("/runners/invocations/", s.handleInvocationSub)
	mux.HandleFunc("/admin/invoke", s.handleAdminInvoke)
	mux.HandleFunc("/admin/state", s.handleAdminState)
	mux.HandleFunc("/healthz", func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte(`{"status":"ok"}`))
	})
	return logRequests(mux, logger)
}

// logRequests wraps the mux to log every request — extremely handy when
// the user wants to see what the runner is doing in real time.
func logRequests(next http.Handler, logger *slog.Logger) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		start := time.Now()
		sw := &statusRecorder{ResponseWriter: w, code: 200}
		next.ServeHTTP(sw, r)
		logger.Info("request",
			slog.String("method", r.Method),
			slog.String("path", r.URL.Path),
			slog.Int("status", sw.code),
			slog.Duration("dur", time.Since(start)))
	})
}

type statusRecorder struct {
	http.ResponseWriter
	code int
}

func (sr *statusRecorder) WriteHeader(code int) { sr.code = code; sr.ResponseWriter.WriteHeader(code) }

// ---------- Runner-facing endpoints ----------

func (s *serverState) handleHeartbeat(w http.ResponseWriter, r *http.Request) {
	token, ok := bearerToken(r)
	if !ok {
		writeAPIErr(w, http.StatusUnauthorized, "missing_auth", "Authorization: Bearer <token> required")
		return
	}
	var req protocol.HeartbeatRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeAPIErr(w, http.StatusBadRequest, "bad_body", err.Error())
		return
	}

	s.mu.Lock()
	row, exists := s.runners[token]
	if !exists {
		row = &runnerRow{token: token}
		s.runners[token] = row
		s.logger.Info("new runner registered",
			slog.String("token_preview", previewToken(token)),
			slog.String("instance_id", req.InstanceID),
			slog.Int("tools", len(req.Tools)))
	}
	row.instanceID = req.InstanceID
	row.lastHB = time.Now()
	row.tools = req.Tools
	row.toolSet = make(map[string]struct{}, len(req.Tools))
	for _, t := range req.Tools {
		row.toolSet[t.Name] = struct{}{}
	}
	s.mu.Unlock()

	writeJSON(w, http.StatusOK, protocol.HeartbeatResponse{})
}

func (s *serverState) handlePoll(w http.ResponseWriter, r *http.Request) {
	token, ok := bearerToken(r)
	if !ok {
		writeAPIErr(w, http.StatusUnauthorized, "missing_auth", "")
		return
	}

	maxWait := 5 * time.Second // dev default; clamped below
	if s := r.URL.Query().Get("max_wait_seconds"); s != "" {
		if n, err := strconv.Atoi(s); err == nil && n > 0 && n <= 60 {
			maxWait = time.Duration(n) * time.Second
		}
	}

	deadline := time.Now().Add(maxWait)
	for {
		inv := s.leaseForToken(token)
		if inv != nil {
			writeJSON(w, http.StatusOK, protocol.PollResponse{Invocation: inv})
			return
		}
		if time.Now().After(deadline) {
			w.WriteHeader(http.StatusNoContent)
			return
		}
		select {
		case <-r.Context().Done():
			w.WriteHeader(http.StatusNoContent)
			return
		case <-time.After(100 * time.Millisecond):
		}
	}
}

// leaseForToken returns the next pending invocation whose tool is in this
// runner's catalog, or nil if none. Moves the invocation from `pending`
// to `awaitingResult` atomically.
func (s *serverState) leaseForToken(token string) *protocol.LeasedInvocation {
	s.mu.Lock()
	defer s.mu.Unlock()
	row, ok := s.runners[token]
	if !ok {
		return nil
	}
	for i, p := range s.pending {
		if _, has := row.toolSet[p.toolName]; !has {
			continue
		}
		s.pending = append(s.pending[:i], s.pending[i+1:]...)
		s.awaitingResult[p.id] = p
		return &protocol.LeasedInvocation{
			ID:                p.id,
			ToolName:          p.toolName,
			Args:              p.args,
			LeaseExpiresAtISO: time.Now().Add(30 * time.Second).Format(time.RFC3339Nano),
		}
	}
	return nil
}

// handleInvocationSub routes /runners/invocations/:id/(result|extend_lease).
func (s *serverState) handleInvocationSub(w http.ResponseWriter, r *http.Request) {
	if _, ok := bearerToken(r); !ok {
		writeAPIErr(w, http.StatusUnauthorized, "missing_auth", "")
		return
	}
	path := strings.TrimPrefix(r.URL.Path, "/runners/invocations/")
	parts := strings.Split(path, "/")
	if len(parts) != 2 {
		http.NotFound(w, r)
		return
	}
	id, op := parts[0], parts[1]
	switch op {
	case "result":
		var body protocol.ResultRequest
		if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
			writeAPIErr(w, http.StatusBadRequest, "bad_body", err.Error())
			return
		}
		s.mu.Lock()
		p, ok := s.awaitingResult[id]
		if ok {
			delete(s.awaitingResult, id)
		}
		s.mu.Unlock()
		if !ok {
			writeAPIErr(w, http.StatusNotFound, "unknown_invocation", id)
			return
		}
		p.result = body.Result
		p.err = body.Error
		close(p.done)
		w.WriteHeader(http.StatusOK)
	case "extend_lease":
		var body protocol.ExtendLeaseRequest
		_ = json.NewDecoder(r.Body).Decode(&body)
		newLease := time.Now().Add(time.Duration(body.ExtendBySeconds) * time.Second).Format(time.RFC3339Nano)
		writeJSON(w, http.StatusOK, protocol.ExtendLeaseResponse{LeaseExpiresAtISO: newLease})
	default:
		http.NotFound(w, r)
	}
}

// ---------- Admin (CLI-facing) endpoints ----------

// adminInvokeRequest is what `fake-posthog invoke` sends.
type adminInvokeRequest struct {
	ToolName       string          `json:"tool_name"`
	Args           json.RawMessage `json:"args"`
	TimeoutSeconds int             `json:"timeout_seconds,omitempty"`
}

// adminInvokeResponse is sent back on POST /admin/invoke. If the work
// failed on the runner side, Status is "failed" and Error is populated.
type adminInvokeResponse struct {
	InvocationID string          `json:"invocation_id"`
	Status       string          `json:"status"` // "done" | "failed" | "timeout"
	Result       json.RawMessage `json:"result,omitempty"`
	Error        string          `json:"error,omitempty"`
}

func (s *serverState) handleAdminInvoke(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		writeAPIErr(w, http.StatusMethodNotAllowed, "method_not_allowed", "")
		return
	}
	var req adminInvokeRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeAPIErr(w, http.StatusBadRequest, "bad_body", err.Error())
		return
	}
	if req.ToolName == "" {
		writeAPIErr(w, http.StatusBadRequest, "missing_tool_name", "tool_name is required")
		return
	}
	timeout := 30 * time.Second
	if req.TimeoutSeconds > 0 {
		timeout = time.Duration(req.TimeoutSeconds) * time.Second
	}

	p := &pendingInvocation{
		id:        newID(),
		toolName:  req.ToolName,
		args:      req.Args,
		createdAt: time.Now(),
		done:      make(chan struct{}),
	}

	s.mu.Lock()
	if !s.anyRunnerServes(req.ToolName) {
		s.mu.Unlock()
		writeAPIErr(w, http.StatusBadRequest, "no_runner_serves_tool",
			fmt.Sprintf("no currently-registered runner advertises %q", req.ToolName))
		return
	}
	s.pending = append(s.pending, p)
	s.mu.Unlock()

	select {
	case <-p.done:
		status := "done"
		if p.err != "" {
			status = "failed"
		}
		writeJSON(w, http.StatusOK, adminInvokeResponse{
			InvocationID: p.id,
			Status:       status,
			Result:       p.result,
			Error:        p.err,
		})
	case <-time.After(timeout):
		// Best-effort: don't try to revoke the invocation; the runner
		// might still post a result that gets dropped. For a dev tool
		// that's acceptable.
		writeJSON(w, http.StatusOK, adminInvokeResponse{
			InvocationID: p.id,
			Status:       "timeout",
			Error:        fmt.Sprintf("no result within %s", timeout),
		})
	}
}

// anyRunnerServes assumes s.mu is held by the caller.
func (s *serverState) anyRunnerServes(toolName string) bool {
	for _, row := range s.runners {
		if _, ok := row.toolSet[toolName]; ok {
			return true
		}
	}
	return false
}

type adminStateResponse struct {
	Runners []runnerSummary `json:"runners"`
	Pending int             `json:"pending_invocations"`
}

type runnerSummary struct {
	TokenPreview     string                    `json:"token_preview"`
	InstanceID       string                    `json:"instance_id"`
	LastHeartbeatISO string                    `json:"last_heartbeat,omitempty"`
	Tools            []protocol.ToolDescriptor `json:"tools"`
}

func (s *serverState) handleAdminState(w http.ResponseWriter, r *http.Request) {
	s.mu.Lock()
	defer s.mu.Unlock()
	resp := adminStateResponse{Pending: len(s.pending)}
	for _, row := range s.runners {
		summary := runnerSummary{
			TokenPreview: previewToken(row.token),
			InstanceID:   row.instanceID,
			Tools:        row.tools,
		}
		if !row.lastHB.IsZero() {
			summary.LastHeartbeatISO = row.lastHB.Format(time.RFC3339Nano)
		}
		resp.Runners = append(resp.Runners, summary)
	}
	writeJSON(w, http.StatusOK, resp)
}

// ---------- Helpers ----------

func bearerToken(r *http.Request) (string, bool) {
	h := r.Header.Get("Authorization")
	if !strings.HasPrefix(h, "Bearer ") {
		return "", false
	}
	t := strings.TrimSpace(strings.TrimPrefix(h, "Bearer "))
	return t, t != ""
}

func previewToken(t string) string {
	if len(t) <= 8 {
		return t
	}
	return t[:4] + "…" + t[len(t)-4:]
}

func newID() string {
	var b [8]byte
	if _, err := rand.Read(b[:]); err != nil {
		return strconv.FormatInt(time.Now().UnixNano(), 16)
	}
	return hex.EncodeToString(b[:])
}

func writeJSON(w http.ResponseWriter, code int, body any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(code)
	_ = json.NewEncoder(w).Encode(body)
}

func writeAPIErr(w http.ResponseWriter, code int, errCode, msg string) {
	writeJSON(w, code, protocol.ErrorResponse{Code: errCode, Message: msg})
}
