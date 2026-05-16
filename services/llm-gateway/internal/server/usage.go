package server

import (
	"github.com/posthog/posthog/services/llm-gateway/internal/products"
	"github.com/posthog/posthog/services/llm-gateway/internal/ratelimit"
	"net/http"
)

func (a *App) usage(w http.ResponseWriter, r *http.Request) {
	req, ok := a.authenticateOnly(w, r)
	if !ok {
		return
	}
	product := products.ResolveAlias(r.PathValue("product"))
	planInfo := a.planResolver.Resolve(r.Context(), req.user.UserID, product, r.Header.Get("Authorization"))
	burst, sustained := a.limiter.Usage(r.Context(), req.user, product, planInfo)
	writeJSON(w, 200, map[string]any{"product": product, "user_id": req.user.UserID, "burst": costStatus(burst), "sustained": costStatus(sustained), "is_rate_limited": burst.Exceeded || sustained.Exceeded})
}

func (a *App) invalidatePlanCache(w http.ResponseWriter, r *http.Request) {
	req, ok := a.authenticateOnly(w, r)
	if !ok {
		return
	}
	if r.PathValue("product") != "posthog_code" {
		writeJSON(w, 404, map[string]string{"detail": "Plan cache not available for this product"})
		return
	}
	a.planResolver.Invalidate(r.Context(), req.user.UserID)
	writeJSON(w, 200, map[string]bool{"ok": true})
}

func costStatus(status ratelimit.Status) map[string]any {
	usedPercent := 0.0
	if status.LimitUSD > 0 {
		usedPercent = status.UsedUSD / status.LimitUSD * 100
		if usedPercent > 100 {
			usedPercent = 100
		}
	}
	return map[string]any{"used_percent": usedPercent, "resets_in_seconds": status.ResetsInSeconds, "exceeded": status.Exceeded}
}
