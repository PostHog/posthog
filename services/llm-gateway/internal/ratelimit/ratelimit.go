package ratelimit

import (
	"context"
	"fmt"
	"strconv"
	"time"

	"github.com/posthog/posthog/services/llm-gateway/internal/auth"
	"github.com/posthog/posthog/services/llm-gateway/internal/config"
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

func (r *Runner) Check(ctx context.Context, user *auth.User, product string, endUserID string) Result {
	if r.redis == nil {
		return Result{Allowed: true}
	}
	productLimit, ok := r.settings.ProductCostLimits[product]
	if ok && productLimit.LimitUSD > 0 {
		used, ttl := r.readWindow(ctx, fmt.Sprintf("llm_gateway:cost:product:%s", product), productLimit.WindowSeconds)
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
	userKey := endUserID
	if userKey == "" {
		userKey = strconv.Itoa(user.UserID)
	}
	if limits.BurstLimitUSD > 0 {
		used, ttl := r.readWindow(ctx, fmt.Sprintf("llm_gateway:cost:user:%s:%s:burst", product, userKey), limits.BurstWindowSeconds)
		if used >= limits.BurstLimitUSD {
			return Result{Allowed: false, Detail: "user_cost_burst_limit", RetryAfter: ttl, StatusCode: 429}
		}
	}
	if limits.SustainedLimitUSD > 0 {
		used, ttl := r.readWindow(ctx, fmt.Sprintf("llm_gateway:cost:user:%s:%s:sustained", product, userKey), limits.SustainedWindowSeconds)
		if used >= limits.SustainedLimitUSD {
			return Result{Allowed: false, Detail: "user_cost_sustained_limit", RetryAfter: ttl, StatusCode: 429}
		}
	}
	return Result{Allowed: true}
}

func (r *Runner) RecordCost(ctx context.Context, user *auth.User, product string, endUserID string, cost float64) {
	if r.redis == nil || cost <= 0 {
		return
	}
	if limit, ok := r.settings.ProductCostLimits[product]; ok {
		r.incrementWindow(ctx, fmt.Sprintf("llm_gateway:cost:product:%s", product), cost, limit.WindowSeconds)
	}
	if r.settings.UserCostLimitsDisabled {
		return
	}
	limits, ok := r.settings.UserCostLimits[product]
	if !ok {
		limits = config.UserCostLimit{BurstLimitUSD: 100, BurstWindowSeconds: 86400, SustainedLimitUSD: 1000, SustainedWindowSeconds: 2592000}
	}
	userKey := endUserID
	if userKey == "" {
		userKey = strconv.Itoa(user.UserID)
	}
	r.incrementWindow(ctx, fmt.Sprintf("llm_gateway:cost:user:%s:%s:burst", product, userKey), cost, limits.BurstWindowSeconds)
	r.incrementWindow(ctx, fmt.Sprintf("llm_gateway:cost:user:%s:%s:sustained", product, userKey), cost, limits.SustainedWindowSeconds)
}

func (r *Runner) Usage(ctx context.Context, user *auth.User, product string) (Status, Status) {
	if r.redis == nil {
		return Status{}, Status{}
	}
	limits, ok := r.settings.UserCostLimits[product]
	if !ok {
		limits = config.UserCostLimit{BurstLimitUSD: 100, BurstWindowSeconds: 86400, SustainedLimitUSD: 1000, SustainedWindowSeconds: 2592000}
	}
	userKey := strconv.Itoa(user.UserID)
	burstUsed, burstTTL := r.readWindow(ctx, fmt.Sprintf("llm_gateway:cost:user:%s:%s:burst", product, userKey), limits.BurstWindowSeconds)
	sustainedUsed, sustainedTTL := r.readWindow(ctx, fmt.Sprintf("llm_gateway:cost:user:%s:%s:sustained", product, userKey), limits.SustainedWindowSeconds)
	return Status{UsedUSD: burstUsed, LimitUSD: limits.BurstLimitUSD, ResetsInSeconds: burstTTL, Exceeded: burstUsed >= limits.BurstLimitUSD}, Status{UsedUSD: sustainedUsed, LimitUSD: limits.SustainedLimitUSD, ResetsInSeconds: sustainedTTL, Exceeded: sustainedUsed >= limits.SustainedLimitUSD}
}

func (r *Runner) readWindow(ctx context.Context, key string, windowSeconds int) (float64, int) {
	value, err := r.redis.Get(ctx, key).Float64()
	if err != nil && err != redis.Nil {
		return 0, windowSeconds
	}
	ttl := r.redis.TTL(ctx, key).Val()
	if ttl <= 0 {
		return value, windowSeconds
	}
	return value, int(ttl.Seconds())
}

func (r *Runner) incrementWindow(ctx context.Context, key string, cost float64, windowSeconds int) {
	pipe := r.redis.TxPipeline()
	pipe.IncrByFloat(ctx, key, cost)
	pipe.ExpireNX(ctx, key, time.Duration(windowSeconds)*time.Second)
	_, _ = pipe.Exec(ctx)
}
