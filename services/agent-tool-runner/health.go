// /healthz endpoint surfaces every runner's State() so k8s probes (or any
// process supervisor) can see when the runner is unable to reach PostHog.
//
// Returns:
//
//	200 OK             — every configured project is `live`
//	503 ServiceUnavailable — at least one project is `connecting` or `degraded`
//
// Body is always JSON, even on 503:
//
//	{
//	  "status": "ok" | "unhealthy",
//	  "projects": [
//	    { "project_id": 123, "slug": "grafana-prod", "state": "live" }
//	  ]
//	}
//
// This is deliberately simple — no per-tool diagnostics, no upstream MCP
// reachability, no tool-call success rates. K8s probes only need a
// binary answer.
package main

import (
	"context"
	"encoding/json"
	"errors"
	"log/slog"
	"net/http"
	"time"

	"github.com/posthog/posthog/services/agent-tool-runner/runner"
)

type healthSnapshot struct {
	Status   string          `json:"status"`
	Projects []projectHealth `json:"projects"`
}

type projectHealth struct {
	ProjectID int    `json:"project_id"`
	Slug      string `json:"slug"`
	State     string `json:"state"`
}

// startHealthServer launches an HTTP server bound to addr in a goroutine.
// Returns a channel closed when the server has shut down — main.run
// waits on this so the process doesn't exit while requests are in flight.
// The server shuts down when ctx is cancelled.
func startHealthServer(ctx context.Context, addr string, prs []projectRunner, logger *slog.Logger) <-chan struct{} {
	done := make(chan struct{})

	mux := http.NewServeMux()
	mux.HandleFunc("/healthz", func(w http.ResponseWriter, r *http.Request) {
		snap := buildSnapshot(prs)
		w.Header().Set("Content-Type", "application/json")
		if snap.Status != "ok" {
			w.WriteHeader(http.StatusServiceUnavailable)
		}
		_ = json.NewEncoder(w).Encode(snap)
	})

	srv := &http.Server{
		Addr:              addr,
		Handler:           mux,
		ReadHeaderTimeout: 5 * time.Second,
	}

	go func() {
		defer close(done)

		listenErr := make(chan error, 1)
		go func() {
			logger.Info("health server listening", slog.String("addr", addr))
			listenErr <- srv.ListenAndServe()
		}()

		select {
		case <-ctx.Done():
			// Graceful shutdown with a bounded deadline so a stuck
			// connection can't keep the process alive forever.
			shutdownCtx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
			defer cancel()
			if err := srv.Shutdown(shutdownCtx); err != nil {
				logger.Warn("health server shutdown error", slog.String("err", err.Error()))
			}
		case err := <-listenErr:
			if err != nil && !errors.Is(err, http.ErrServerClosed) {
				logger.Warn("health server failed", slog.String("err", err.Error()))
			}
		}
	}()

	return done
}

func buildSnapshot(prs []projectRunner) healthSnapshot {
	snap := healthSnapshot{
		Status:   "ok",
		Projects: make([]projectHealth, 0, len(prs)),
	}
	for _, pr := range prs {
		s := pr.runner.State()
		snap.Projects = append(snap.Projects, projectHealth{
			ProjectID: pr.project.ProjectID,
			Slug:      pr.project.Slug,
			State:     string(s),
		})
		if s != runner.StateLive {
			snap.Status = "unhealthy"
		}
	}
	return snap
}
