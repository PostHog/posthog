package services

import (
	"context"
	"encoding/json"
	"net/http"
	"strconv"
	"strings"
	"time"

	"github.com/posthog/posthog/services/llm-gateway/internal/config"
	"github.com/posthog/posthog/services/llm-gateway/internal/metrics"
	"github.com/redis/go-redis/v9"
)

const PostHogCodeProduct = "posthog_code"

var proPlanPrefixes = []string{"posthog-code-200", "posthog-code-pro-"}

type BillingPeriod struct {
	CurrentPeriodStart string `json:"current_period_start"`
	CurrentPeriodEnd   string `json:"current_period_end"`
	Interval           string `json:"interval"`
}

type PlanInfo struct {
	PlanKey       string         `json:"plan_key"`
	SeatCreatedAt string         `json:"created_at"`
	BillingPeriod *BillingPeriod `json:"billing_period,omitempty"`
}

type PlanResolver struct {
	redis      *redis.Client
	settings   *config.Settings
	httpClient *http.Client
}

func NewPlanResolver(redisClient *redis.Client, settings *config.Settings) *PlanResolver {
	return &PlanResolver{redis: redisClient, settings: settings, httpClient: &http.Client{Timeout: 2 * time.Second}}
}

func IsProPlan(planKey string) bool {
	for _, prefix := range proPlanPrefixes {
		if strings.HasPrefix(planKey, prefix) {
			return true
		}
	}
	return false
}

func BillingPeriodNumber(seatCreatedAt string, periodDays int, billingPeriodStart string) int {
	anchor := billingPeriodStart
	if anchor == "" {
		anchor = seatCreatedAt
	}
	if anchor == "" {
		return 0
	}
	created, err := time.Parse(time.RFC3339, anchor)
	if err != nil {
		created, err = time.Parse("2006-01-02T15:04:05", anchor)
	}
	if err != nil {
		return 0
	}
	elapsed := int(time.Since(created).Hours() / 24)
	if elapsed < 0 || periodDays <= 0 {
		return 0
	}
	return elapsed / periodDays
}

func (r *PlanResolver) Resolve(ctx context.Context, userID int, product string, authHeader string) PlanInfo {
	if product != PostHogCodeProduct || authHeader == "" {
		return PlanInfo{}
	}
	if cached, ok := r.getCached(ctx, userID); ok {
		return cached
	}
	info, ok := r.fetch(ctx, authHeader)
	if !ok {
		return PlanInfo{}
	}
	r.setCached(ctx, userID, info)
	return info
}

func (r *PlanResolver) Invalidate(ctx context.Context, userID int) {
	if r.redis == nil {
		return
	}
	if err := r.redis.Del(ctx, planKey(userID)).Err(); err != nil {
		metrics.RedisFallback.Inc()
	}
}

func (r *PlanResolver) getCached(ctx context.Context, userID int) (PlanInfo, bool) {
	if r.redis == nil {
		return PlanInfo{}, false
	}
	value, err := r.redis.Get(ctx, planKey(userID)).Bytes()
	if err != nil {
		if err != redis.Nil {
			metrics.RedisFallback.Inc()
		}
		return PlanInfo{}, false
	}
	var info PlanInfo
	if err := json.Unmarshal(value, &info); err != nil {
		return PlanInfo{}, false
	}
	return info, true
}

func (r *PlanResolver) setCached(ctx context.Context, userID int, info PlanInfo) {
	if r.redis == nil {
		return
	}
	payload, err := json.Marshal(info)
	if err != nil {
		return
	}
	if err := r.redis.Set(ctx, planKey(userID), payload, r.settings.PlanCacheTTL).Err(); err != nil {
		metrics.RedisFallback.Inc()
	}
}

func (r *PlanResolver) fetch(ctx context.Context, authHeader string) (PlanInfo, bool) {
	if r.settings.PostHogAPIBaseURL == "" {
		return PlanInfo{}, true
	}
	url := strings.TrimRight(r.settings.PostHogAPIBaseURL, "/") + "/api/seats/me/?product_key=posthog_code&best=true"
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, url, nil)
	if err != nil {
		return PlanInfo{}, false
	}
	req.Header.Set("Authorization", authHeader)
	resp, err := r.httpClient.Do(req)
	if err != nil {
		return PlanInfo{}, false
	}
	defer resp.Body.Close()
	if resp.StatusCode == http.StatusNotFound {
		return PlanInfo{}, true
	}
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return PlanInfo{}, false
	}
	var info PlanInfo
	if err := json.NewDecoder(resp.Body).Decode(&info); err != nil {
		return PlanInfo{}, false
	}
	return info, true
}

func planKey(userID int) string { return "plan:posthog_code:" + strconv.Itoa(userID) }
