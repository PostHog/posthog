package server

import (
	"context"
	"net/http"
	"time"
)

func (a *App) root(w http.ResponseWriter, r *http.Request) {
	writeJSON(w, 200, map[string]string{"service": "llm-gateway", "status": "running"})
}

func (a *App) liveness(w http.ResponseWriter, r *http.Request) {
	writeJSON(w, 200, map[string]string{"status": "alive"})
}

func (a *App) readiness(w http.ResponseWriter, r *http.Request) {
	ctx, cancel := context.WithTimeout(r.Context(), 2*time.Second)
	defer cancel()
	if err := a.db.Ping(ctx); err != nil {
		writeJSON(w, 503, map[string]string{"detail": "Database not ready"})
		return
	}
	writeJSON(w, 200, map[string]string{"status": "ready"})
}
