package ratelimit

import (
	"math"
	"testing"
	"time"
)

func TestLimiterRefillsTokens(t *testing.T) {
	now := time.Unix(100, 0)
	limiter, err := newLimiter(Config{Capacity: 2, RefillPerSec: 1, MaxEntries: 2, IdleTTL: time.Minute}, func() time.Time { return now })
	if err != nil {
		t.Fatal(err)
	}
	for range 2 {
		if allowed, _ := limiter.Allow("scope"); !allowed {
			t.Fatal("request was unexpectedly limited")
		}
	}
	if allowed, retryAfter := limiter.Allow("scope"); allowed || retryAfter != time.Second {
		t.Fatalf("expected one second retry, got allowed=%t retry=%s", allowed, retryAfter)
	}
	now = now.Add(time.Second)
	if allowed, _ := limiter.Allow("scope"); !allowed {
		t.Fatal("refilled request was limited")
	}
}

func TestLimiterBoundsKeysAndEvictsLeastRecentlyUsed(t *testing.T) {
	now := time.Unix(100, 0)
	limiter, err := newLimiter(Config{Capacity: 2, RefillPerSec: 1, MaxEntries: 2, IdleTTL: time.Minute}, func() time.Time { return now })
	if err != nil {
		t.Fatal(err)
	}
	limiter.Allow("first")
	now = now.Add(time.Second)
	limiter.Allow("second")
	now = now.Add(time.Second)
	limiter.Allow("first")
	now = now.Add(time.Second)
	limiter.Allow("third")

	if len(limiter.entries) != 2 || limiter.entries["first"] == nil || limiter.entries["third"] == nil {
		t.Fatalf("unexpected bounded entries: %#v", limiter.entries)
	}
	if limiter.entries["second"] != nil {
		t.Fatal("least recently used key was not evicted")
	}
}

func TestLimiterRejectsNonFiniteValues(t *testing.T) {
	for _, config := range []Config{
		{Capacity: math.NaN(), RefillPerSec: 1, MaxEntries: 1, IdleTTL: time.Minute},
		{Capacity: 1, RefillPerSec: math.Inf(1), MaxEntries: 1, IdleTTL: time.Minute},
	} {
		if _, err := New(config); err == nil {
			t.Fatal("non-finite configuration was accepted")
		}
	}
}
