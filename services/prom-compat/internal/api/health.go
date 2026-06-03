package api

import (
	"context"
	"encoding/json"
	"net/http"
	"time"
)

const readinessTimeout = 2 * time.Second

type readinessBody struct {
	Status     string `json:"status"`
	ClickHouse string `json:"clickhouse,omitempty"`
	Error      string `json:"error,omitempty"`
}

func readinessHandler(deps Deps) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if deps.Storage == nil {
			writeJSON(w, http.StatusOK, readinessBody{Status: "ok"})
			return
		}
		ctx, cancel := context.WithTimeout(r.Context(), readinessTimeout)
		defer cancel()
		if err := deps.Storage.Ping(ctx); err != nil {
			writeJSON(w, http.StatusServiceUnavailable, readinessBody{
				Status:     "degraded",
				ClickHouse: "unreachable",
				Error:      err.Error(),
			})
			return
		}
		writeJSON(w, http.StatusOK, readinessBody{Status: "ok", ClickHouse: "ok"})
	}
}

func livenessHandler(w http.ResponseWriter, _ *http.Request) {
	writeJSON(w, http.StatusOK, readinessBody{Status: "ok"})
}

func writeJSON(w http.ResponseWriter, status int, body any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(body)
}
