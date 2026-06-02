package api

import (
	"net/http"

	"github.com/go-chi/chi/v5"
	"github.com/go-chi/chi/v5/middleware"
	"github.com/prometheus/client_golang/prometheus/promhttp"
)

// NewServer constructs the prom-compat HTTP handler tree.
// PR 1 ships only health and self-metrics endpoints; PromQL routes land in PR 5.
func NewServer() http.Handler {
	r := chi.NewRouter()

	r.Use(middleware.RequestID)
	r.Use(middleware.Recoverer)

	r.Get("/_readiness", readinessHandler)
	r.Get("/_liveness", livenessHandler)
	r.Handle("/metrics", promhttp.Handler())

	return r
}
