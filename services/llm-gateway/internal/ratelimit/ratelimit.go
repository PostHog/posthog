package ratelimit

import (
	"context"
	"fmt"
	"strconv"
	"time"

	"github.com/posthog/posthog/services/llm-gateway/internal/auth"
	"github.com/posthog/posthog/services/llm-gateway/internal/config"
	"github.com/posthog/posthog/services/llm-gateway/internal/metrics"
	"github.com/posthog/posthog/services/llm-gateway/internal/services"
	"github.com/redis/go-redis/v9"
)

type Result struct {
	Allowed    bool
	Detail     string
	RetryAfter int
	StatusCode int
}

type Status struct {
	UsedUSD         float64
	LimitUSD        float64
	ResetsInSeconds int
	Exceeded        bool
}

type Runner struct {
	redis    *redis.Client
	settings *config.Settings
}

func New(redisClient *redis.Client, settings *config.Settings) *Runner {
	return &Runner{redis: redisClient, settings: settings}
}

func (r *Runner) Check(ctx context.Context, user *auth.User, product string, endUserID string, planInfo services.PlanInfo) Result {
	if r.redis == nil {
		return Result{Allowed: true}
	}
	productLimit, ok := r.settings.ProductCostLimits[product]
	if !ok {
		productLimit = config.ProductCostLimit{LimitUSD: 1000, WindowSeconds: 86400}
	}
	if productLimit.LimitUSD > 0 {
		productLimit.LimitUSD *= float64(teamMultiplier(r.settings, user))
		used, ttl := r.readWindow(ctx, productKey(product, teamMultiplier(r.settings, user)), productLimit.WindowSeconds)
		if used >= productLimit.LimitUSD {
			return Result{Allowed: false, Detail: "product_cost_limit", RetryAfter: ttl, StatusCode: 429}
		}
	}
	if r.settings.UserCostLimitsDisabled {
		return Result{Allowed: true}
	}
	limits, ok := r.settings.UserCostLimits[product]
	if !ok {
		limits = config.UserCostLimit{BurstLimitUSD: 100, BurstWindowSeconds: 86400, SustainedLimitUSD: 1000, SustainedWindowSeconds: 2592000}
	}
	if product == services.PostHogCodeProduct && planInfo.SeatCreatedAt != "" && !services.IsProPlan(planInfo.PlanKey) {
		limits = config.UserCostLimit{BurstLimitUSD: 50, BurstWindowSeconds: 86400, SustainedLimitUSD: 50, SustainedWindowSeconds: 2592000}
	}
	multiplier := float64(teamMultiplier(r.settings, user))
	limits.BurstLimitUSD *= multiplier
	limits.SustainedLimitUSD *= multiplier
	userKey := endUserID
	if userKey == "" {
		return Result{Allowed: true}
	}
	if limits.BurstLimitUSD > 0 {
		used, ttl := r.readWindow(ctx, userKeyFor("user_cost_burst", product, userKey, teamMultiplier(r.settings, user), -1), limits.BurstWindowSeconds)
		if used >= limits.BurstLimitUSD {
			return Result{Allowed: false, Detail: "user_cost_burst_limit", RetryAfter: ttl, StatusCode: 429}
		}
	}
	if limits.SustainedLimitUSD > 0 {
		used, ttl := r.readWindow(ctx, userKeyFor("user_cost_sustained", product, userKey, teamMultiplier(r.settings, user), sustainedPeriod(product, planInfo, r.settings.BillingPeriodDays)), limits.SustainedWindowSeconds)
		if used >= limits.SustainedLimitUSD {
			return Result{Allowed: false, Detail: "user_cost_sustained_limit", RetryAfter: ttl, StatusCode: 429}
		}
	}
	return Result{Allowed: true}
}

func (r *Runner) RecordCost(ctx context.Context, user *auth.User, product string, endUserID string, cost float64, planInfo services.PlanInfo) {
	if r.redis == nil || cost <= 0 {
		if r.redis == nil {
			metrics.RedisFallback.Inc()
		}
		return
	}
	limit, ok := r.settings.ProductCostLimits[product]
	if !ok {
		limit = config.ProductCostLimit{LimitUSD: 1000, WindowSeconds: 86400}
	}
	r.incrementWindow(ctx, productKey(product, teamMultiplier(r.settings, user)), cost, limit.WindowSeconds)
	if r.settings.UserCostLimitsDisabled {
		return
	}
	limits, ok := r.settings.UserCostLimits[product]
	if !ok {
		limits = config.UserCostLimit{BurstLimitUSD: 100, BurstWindowSeconds: 86400, SustainedLimitUSD: 1000, SustainedWindowSeconds: 2592000}
	}
	userKey := endUserID
	if userKey == "" {
		return
	}
	r.incrementWindow(ctx, userKeyFor("user_cost_burst", product, userKey, teamMultiplier(r.settings, user), -1), cost, limits.BurstWindowSeconds)
	r.incrementWindow(ctx, userKeyFor("user_cost_sustained", product, userKey, teamMultiplier(r.settings, user), sustainedPeriod(product, planInfo, r.settings.BillingPeriodDays)), cost, limits.SustainedWindowSeconds)
}

func (r *Runner) Usage(ctx context.Context, user *auth.User, product string, planInfo services.PlanInfo) (Status, Status) {
	if r.redis == nil {
		return Status{}, Status{}
	}
	limits, ok := r.settings.UserCostLimits[product]
	if !ok {
		limits = config.UserCostLimit{BurstLimitUSD: 100, BurstWindowSeconds: 86400, SustainedLimitUSD: 1000, SustainedWindowSeconds: 2592000}
	}
	if product == services.PostHogCodeProduct && planInfo.SeatCreatedAt != "" && !services.IsProPlan(planInfo.PlanKey) {
		limits = config.UserCostLimit{BurstLimitUSD: 50, BurstWindowSeconds: 86400, SustainedLimitUSD: 50, SustainedWindowSeconds: 2592000}
	}
	userKey := strconv.Itoa(user.UserID)
	burstUsed, burstTTL := r.readWindow(ctx, userKeyFor("user_cost_burst", product, userKey, teamMultiplier(r.settings, user), -1), limits.BurstWindowSeconds)
	sustainedUsed, sustainedTTL := r.readWindow(ctx, userKeyFor("user_cost_sustained", product, userKey, teamMultiplier(r.settings, user), sustainedPeriod(product, planInfo, r.settings.BillingPeriodDays)), limits.SustainedWindowSeconds)
	return Status{UsedUSD: burstUsed, LimitUSD: limits.BurstLimitUSD, ResetsInSeconds: burstTTL, Exceeded: burstUsed >= limits.BurstLimitUSD}, Status{UsedUSD: sustainedUsed, LimitUSD: limits.SustainedLimitUSD, ResetsInSeconds: sustainedTTL, Exceeded: sustainedUsed >= limits.SustainedLimitUSD}
}

func (r *Runner) readWindow(ctx context.Context, key string, windowSeconds int) (float64, int) {
	redisKey := "ratelimit:" + key
	value, err := r.redis.Get(ctx, redisKey).Float64()
	if err != nil && err != redis.Nil {
		metrics.RedisFallback.Inc()
		return 0, windowSeconds
	}
	ttl := r.redis.TTL(ctx, redisKey).Val()
	if ttl <= 0 {
		return value, windowSeconds
	}
	return value, int(ttl.Seconds())
}

func (r *Runner) incrementWindow(ctx context.Context, key string, cost float64, windowSeconds int) {
	redisKey := "ratelimit:" + key
	pipe := r.redis.TxPipeline()
	pipe.IncrByFloat(ctx, redisKey, cost)
	pipe.ExpireNX(ctx, redisKey, time.Duration(windowSeconds)*time.Second)
	if _, err := pipe.Exec(ctx); err != nil {
		metrics.RedisFallback.Inc()
	}
}

func productKey(product string, teamMult int) string {
	base := "cost:product:" + product
	if teamMult > 1 {
		base += fmt.Sprintf(":tm%d", teamMult)
	}
	return base
}

func userKeyFor(scope string, product string, endUserID string, teamMult int, period int) string {
	base := fmt.Sprintf("cost:user:%s:%s:%s", scope, product, endUserID)
	if teamMult > 1 {
		base += fmt.Sprintf(":tm%d", teamMult)
	}
	if period >= 0 {
		base += fmt.Sprintf(":period:%d", period)
	}
	return base
}

func sustainedPeriod(product string, planInfo services.PlanInfo, billingPeriodDays int) int {
	if product != services.PostHogCodeProduct {
		return -1
	}
	billingStart := ""
	if planInfo.BillingPeriod != nil {
		billingStart = planInfo.BillingPeriod.CurrentPeriodStart
	}
	return services.BillingPeriodNumber(planInfo.SeatCreatedAt, billingPeriodDays, billingStart)
}

func teamMultiplier(settings *config.Settings, user *auth.User) int {
	if user == nil || user.TeamID == nil {
		return 1
	}
	if multiplier, ok := settings.TeamRateLimitMultipliers[*user.TeamID]; ok && multiplier > 0 {
		return multiplier
	}
	return 1
}
