package api

import (
	"net/http"

	"github.com/go-chi/chi/v5"
	"github.com/go-chi/chi/v5/middleware"
	"github.com/prometheus/client_golang/prometheus/promhttp"

	"github.com/posthog/posthog/services/prom-compat/internal/storage"
)

// Deps gathers the components a Server depends on.
// Subsequent PRs add fields here (auth resolver, tenant resolver, PromQL engine).
type Deps struct {
	// Storage is the ClickHouse client used by /_readiness and (later) the
	// PromQL storage adapter. A nil Storage disables the CH health check.
	Storage *storage.Client
}

// NewServer constructs the prom-compat HTTP handler tree.
func NewServer(deps Deps) http.Handler {
	r := chi.NewRouter()

	r.Use(middleware.RequestID)
	r.Use(middleware.Recoverer)

	r.Get("/_readiness", readinessHandler(deps))
	r.Get("/_liveness", livenessHandler)
	r.Handle("/metrics", promhttp.Handler())

	return r
}
