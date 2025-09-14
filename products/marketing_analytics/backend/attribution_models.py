"""
Attribution Models for Marketing Analytics

This module provides various attribution models for analyzing marketing touchpoints
and assigning credit to different channels in the customer journey.
"""

from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from datetime import datetime, timedelta
import math

from posthog.hogql import ast
from posthog.hogql.parser import parse_expr


@dataclass
class TouchPoint:
    """Represents a marketing touchpoint in a customer journey"""
    timestamp: datetime
    utm_source: str
    utm_medium: str
    utm_campaign: str
    person_id: str
    revenue: Optional[float] = None
    event: str = ""


@dataclass
class AttributionResult:
    """Result of attribution analysis"""
    source: str
    medium: str
    campaign: str
    attributed_conversions: float
    attributed_revenue: float
    touch_points: int


class AttributionModel:
    """Base class for attribution models"""
    
    def __init__(self, conversion_window_days: int = 30):
        self.conversion_window_days = conversion_window_days
    
    def calculate_attribution(self, touchpoints: List[TouchPoint]) -> List[AttributionResult]:
        """Calculate attribution based on the model"""
        raise NotImplementedError


class FirstTouchAttributionModel(AttributionModel):
    """First-touch attribution model - gives 100% credit to first touchpoint"""
    
    def calculate_attribution(self, touchpoints: List[TouchPoint]) -> List[AttributionResult]:
        # Group touchpoints by person
        person_touchpoints = {}
        for tp in touchpoints:
            if tp.person_id not in person_touchpoints:
                person_touchpoints[tp.person_id] = []
            person_touchpoints[tp.person_id].append(tp)
        
        # Find first touchpoint for each person and attribute all revenue
        results = {}
        for person_id, tps in person_touchpoints.items():
            # Sort by timestamp to find first touchpoint
            tps.sort(key=lambda x: x.timestamp)
            first_tp = tps[0]
            
            # Get total revenue for this person (from conversion events)
            total_revenue = sum(tp.revenue or 0 for tp in tps if tp.revenue)
            
            key = (first_tp.utm_source, first_tp.utm_medium, first_tp.utm_campaign)
            if key not in results:
                results[key] = AttributionResult(
                    source=first_tp.utm_source,
                    medium=first_tp.utm_medium,
                    campaign=first_tp.utm_campaign,
                    attributed_conversions=0,
                    attributed_revenue=0,
                    touch_points=0
                )
            
            results[key].attributed_conversions += 1
            results[key].attributed_revenue += total_revenue
            results[key].touch_points += len(tps)
        
        return list(results.values())


class LastTouchAttributionModel(AttributionModel):
    """Last-touch attribution model - gives 100% credit to last touchpoint before conversion"""
    
    def calculate_attribution(self, touchpoints: List[TouchPoint]) -> List[AttributionResult]:
        person_touchpoints = {}
        for tp in touchpoints:
            if tp.person_id not in person_touchpoints:
                person_touchpoints[tp.person_id] = []
            person_touchpoints[tp.person_id].append(tp)
        
        results = {}
        for person_id, tps in person_touchpoints.items():
            # Sort by timestamp and find last touchpoint before conversion
            tps.sort(key=lambda x: x.timestamp)
            
            # Find the last touchpoint with marketing data before conversion
            last_marketing_tp = None
            total_revenue = 0
            
            for tp in reversed(tps):
                if tp.revenue:
                    total_revenue += tp.revenue
                if tp.utm_source and not last_marketing_tp:
                    last_marketing_tp = tp
            
            if last_marketing_tp:
                key = (last_marketing_tp.utm_source, last_marketing_tp.utm_medium, last_marketing_tp.utm_campaign)
                if key not in results:
                    results[key] = AttributionResult(
                        source=last_marketing_tp.utm_source,
                        medium=last_marketing_tp.utm_medium,
                        campaign=last_marketing_tp.utm_campaign,
                        attributed_conversions=0,
                        attributed_revenue=0,
                        touch_points=0
                    )
                
                results[key].attributed_conversions += 1
                results[key].attributed_revenue += total_revenue
                results[key].touch_points += len(tps)
        
        return list(results.values())


class LinearAttributionModel(AttributionModel):
    """Linear attribution model - distributes credit equally across all touchpoints"""
    
    def calculate_attribution(self, touchpoints: List[TouchPoint]) -> List[AttributionResult]:
        person_touchpoints = {}
        for tp in touchpoints:
            if tp.person_id not in person_touchpoints:
                person_touchpoints[tp.person_id] = []
            person_touchpoints[tp.person_id].append(tp)
        
        results = {}
        for person_id, tps in person_touchpoints.items():
            # Find marketing touchpoints and total revenue
            marketing_tps = [tp for tp in tps if tp.utm_source]
            total_revenue = sum(tp.revenue or 0 for tp in tps if tp.revenue)
            
            if marketing_tps and total_revenue > 0:
                # Distribute revenue equally across marketing touchpoints
                revenue_per_touchpoint = total_revenue / len(marketing_tps)
                conversion_credit = 1.0 / len(marketing_tps)
                
                for tp in marketing_tps:
                    key = (tp.utm_source, tp.utm_medium, tp.utm_campaign)
                    if key not in results:
                        results[key] = AttributionResult(
                            source=tp.utm_source,
                            medium=tp.utm_medium,
                            campaign=tp.utm_campaign,
                            attributed_conversions=0,
                            attributed_revenue=0,
                            touch_points=0
                        )
                    
                    results[key].attributed_conversions += conversion_credit
                    results[key].attributed_revenue += revenue_per_touchpoint
                    results[key].touch_points += 1
        
        return list(results.values())


class TimeDecayAttributionModel(AttributionModel):
    """Time-decay attribution model - gives more credit to touchpoints closer to conversion"""
    
    def __init__(self, conversion_window_days: int = 30, decay_rate: float = 0.1):
        super().__init__(conversion_window_days)
        self.decay_rate = decay_rate  # Higher values = faster decay
    
    def calculate_attribution(self, touchpoints: List[TouchPoint]) -> List[AttributionResult]:
        person_touchpoints = {}
        for tp in touchpoints:
            if tp.person_id not in person_touchpoints:
                person_touchpoints[tp.person_id] = []
            person_touchpoints[tp.person_id].append(tp)
        
        results = {}
        for person_id, tps in person_touchpoints.items():
            tps.sort(key=lambda x: x.timestamp)
            
            # Find conversion timestamp (last event with revenue)
            conversion_time = None
            total_revenue = 0
            for tp in reversed(tps):
                if tp.revenue:
                    total_revenue += tp.revenue
                    if not conversion_time:
                        conversion_time = tp.timestamp
            
            if not conversion_time or total_revenue <= 0:
                continue
            
            # Calculate time-decay weights for marketing touchpoints
            marketing_tps = [tp for tp in tps if tp.utm_source]
            weights = []
            
            for tp in marketing_tps:
                days_before_conversion = (conversion_time - tp.timestamp).days
                # Use exponential decay: weight = e^(-decay_rate * days)
                weight = math.exp(-self.decay_rate * days_before_conversion)
                weights.append(weight)
            
            if not weights:
                continue
            
            # Normalize weights to sum to 1
            total_weight = sum(weights)
            normalized_weights = [w / total_weight for w in weights]
            
            # Distribute revenue based on weights
            for tp, weight in zip(marketing_tps, normalized_weights):
                key = (tp.utm_source, tp.utm_medium, tp.utm_campaign)
                if key not in results:
                    results[key] = AttributionResult(
                        source=tp.utm_source,
                        medium=tp.utm_medium,
                        campaign=tp.utm_campaign,
                        attributed_conversions=0,
                        attributed_revenue=0,
                        touch_points=0
                    )
                
                results[key].attributed_conversions += weight
                results[key].attributed_revenue += total_revenue * weight
                results[key].touch_points += 1
        
        return list(results.values())


class PositionBasedAttributionModel(AttributionModel):
    """Position-based attribution model - gives more credit to first and last touchpoints"""
    
    def __init__(self, conversion_window_days: int = 30, first_weight: float = 0.4, 
                 last_weight: float = 0.4, middle_weight: float = 0.2):
        super().__init__(conversion_window_days)
        self.first_weight = first_weight
        self.last_weight = last_weight
        self.middle_weight = middle_weight
    
    def calculate_attribution(self, touchpoints: List[TouchPoint]) -> List[AttributionResult]:
        person_touchpoints = {}
        for tp in touchpoints:
            if tp.person_id not in person_touchpoints:
                person_touchpoints[tp.person_id] = []
            person_touchpoints[tp.person_id].append(tp)
        
        results = {}
        for person_id, tps in person_touchpoints.items():
            marketing_tps = [tp for tp in tps if tp.utm_source]
            marketing_tps.sort(key=lambda x: x.timestamp)
            
            total_revenue = sum(tp.revenue or 0 for tp in tps if tp.revenue)
            
            if len(marketing_tps) < 2 or total_revenue <= 0:
                continue
            
            # Assign weights based on position
            weights = [0] * len(marketing_tps)
            weights[0] = self.first_weight  # First touchpoint
            weights[-1] = self.last_weight  # Last touchpoint
            
            # Distribute middle weight across remaining touchpoints
            if len(marketing_tps) > 2:
                middle_weight_per_tp = self.middle_weight / (len(marketing_tps) - 2)
                for i in range(1, len(marketing_tps) - 1):
                    weights[i] = middle_weight_per_tp
            
            # Distribute revenue based on weights
            for tp, weight in zip(marketing_tps, weights):
                key = (tp.utm_source, tp.utm_medium, tp.utm_campaign)
                if key not in results:
                    results[key] = AttributionResult(
                        source=tp.utm_source,
                        medium=tp.utm_medium,
                        campaign=tp.utm_campaign,
                        attributed_conversions=0,
                        attributed_revenue=0,
                        touch_points=0
                    )
                
                results[key].attributed_conversions += weight
                results[key].attributed_revenue += total_revenue * weight
                results[key].touch_points += 1
        
        return list(results.values())


class AttributionAnalyzer:
    """Main class for running attribution analysis"""
    
    def __init__(self, team_id: int):
        self.team_id = team_id
        self.models = {
            'first_touch': FirstTouchAttributionModel(),
            'last_touch': LastTouchAttributionModel(),
            'linear': LinearAttributionModel(),
            'time_decay': TimeDecayAttributionModel(),
            'position_based': PositionBasedAttributionModel(),
        }
    
    def get_touchpoints_query(self, conversion_events: List[str], 
                            days: int = 30) -> str:
        """Generate HogQL query to fetch touchpoint data"""
        
        conversion_events_str = ', '.join(f"'{event}'" for event in conversion_events)
        
        query = f"""
        WITH touchpoint_events AS (
            SELECT 
                person_id,
                event,
                timestamp,
                properties.utm_source as utm_source,
                properties.utm_medium as utm_medium,
                properties.utm_campaign as utm_campaign,
                properties.revenue as revenue,
                properties.gclid as google_click_id,
                properties.fbclid as facebook_click_id
            FROM events 
            WHERE timestamp >= now() - interval {days} day
            AND (
                -- Include conversion events
                event IN ({conversion_events_str})
                -- Include any event with marketing attribution
                OR properties.utm_source IS NOT NULL
                OR properties.gclid IS NOT NULL
                OR properties.fbclid IS NOT NULL
                -- Include pageviews from marketing channels
                OR (event = '$pageview' AND properties.$referrer LIKE '%google.com%')
                OR (event = '$pageview' AND properties.$referrer LIKE '%facebook.com%')
                OR (event = '$pageview' AND properties.$referrer LIKE '%instagram.com%')
                OR (event = '$pageview' AND properties.$referrer LIKE '%linkedin.com%')
                OR (event = '$pageview' AND properties.$referrer LIKE '%bing.com%')
            )
        ),
        enriched_touchpoints AS (
            SELECT 
                *,
                -- Derive utm_source from referrer if not set
                CASE 
                    WHEN utm_source IS NOT NULL THEN utm_source
                    WHEN google_click_id IS NOT NULL THEN 'google'
                    WHEN facebook_click_id IS NOT NULL THEN 'facebook'
                    WHEN properties.$referrer LIKE '%google.com%' THEN 'google'
                    WHEN properties.$referrer LIKE '%facebook.com%' THEN 'facebook'
                    WHEN properties.$referrer LIKE '%instagram.com%' THEN 'instagram'
                    WHEN properties.$referrer LIKE '%linkedin.com%' THEN 'linkedin'
                    WHEN properties.$referrer LIKE '%bing.com%' THEN 'bing'
                    ELSE 'direct'
                END as derived_utm_source,
                -- Derive utm_medium if not set
                CASE 
                    WHEN utm_medium IS NOT NULL THEN utm_medium
                    WHEN google_click_id IS NOT NULL THEN 'cpc'
                    WHEN facebook_click_id IS NOT NULL THEN 'social'
                    WHEN properties.$referrer IS NOT NULL THEN 'referral'
                    ELSE 'direct'
                END as derived_utm_medium
            FROM touchpoint_events
        )
        SELECT 
            person_id,
            event,
            timestamp,
            derived_utm_source as utm_source,
            derived_utm_medium as utm_medium,
            coalesce(utm_campaign, 'unknown') as utm_campaign,
            revenue
        FROM enriched_touchpoints
        WHERE derived_utm_source IS NOT NULL
        ORDER BY person_id, timestamp
        """
        
        return query
    
    def run_attribution_analysis(self, model_name: str, conversion_events: List[str], 
                               days: int = 30) -> List[AttributionResult]:
        """Run attribution analysis for a specific model"""
        
        if model_name not in self.models:
            raise ValueError(f"Unknown attribution model: {model_name}")
        
        # In a real implementation, this would execute the HogQL query
        # and convert results to TouchPoint objects
        # For now, returning mock data
        
        model = self.models[model_name]
        
        # Mock touchpoints for demonstration
        mock_touchpoints = [
            TouchPoint(
                timestamp=datetime.now() - timedelta(days=5),
                utm_source='google',
                utm_medium='cpc',
                utm_campaign='brand-campaign',
                person_id='user1',
                revenue=100.0,
                event='purchase'
            ),
            TouchPoint(
                timestamp=datetime.now() - timedelta(days=10),
                utm_source='facebook',
                utm_medium='social',
                utm_campaign='awareness-campaign',
                person_id='user1',
                event='$pageview'
            ),
        ]
        
        return model.calculate_attribution(mock_touchpoints)
    
    def compare_attribution_models(self, conversion_events: List[str], 
                                 days: int = 30) -> Dict[str, List[AttributionResult]]:
        """Compare results across all attribution models"""
        
        results = {}
        for model_name in self.models.keys():
            results[model_name] = self.run_attribution_analysis(model_name, conversion_events, days)
        
        return results


def generate_attribution_hogql_query(model_type: str, conversion_events: List[str], 
                                   days: int = 30, conversion_window_days: int = 30) -> str:
    """Generate HogQL query for attribution analysis that can be used in insights"""
    
    conversion_events_str = ', '.join(f"'{event}'" for event in conversion_events)
    
    if model_type == 'first_touch':
        return f"""
        WITH first_touch_attribution AS (
            SELECT 
                person_id,
                first_value(properties.utm_source) OVER (
                    PARTITION BY person_id 
                    ORDER BY timestamp 
                    ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING
                ) as first_utm_source,
                first_value(properties.utm_campaign) OVER (
                    PARTITION BY person_id 
                    ORDER BY timestamp 
                    ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING
                ) as first_utm_campaign,
                sum(properties.revenue) as total_revenue,
                countIf(event IN ({conversion_events_str})) as conversions
            FROM events 
            WHERE timestamp >= now() - interval {days} day
            AND (
                event IN ({conversion_events_str})
                OR properties.utm_source IS NOT NULL
            )
            GROUP BY person_id
        )
        SELECT 
            first_utm_source as utm_source,
            first_utm_campaign as utm_campaign,
            sum(conversions) as attributed_conversions,
            sum(total_revenue) as attributed_revenue,
            count() as unique_customers
        FROM first_touch_attribution
        WHERE first_utm_source IS NOT NULL
        GROUP BY first_utm_source, first_utm_campaign
        ORDER BY attributed_revenue DESC
        """
    
    elif model_type == 'last_touch':
        return f"""
        WITH last_touch_attribution AS (
            SELECT 
                person_id,
                last_value(properties.utm_source) OVER (
                    PARTITION BY person_id 
                    ORDER BY timestamp 
                    ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING
                ) as last_utm_source,
                last_value(properties.utm_campaign) OVER (
                    PARTITION BY person_id 
                    ORDER BY timestamp 
                    ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING
                ) as last_utm_campaign,
                sum(properties.revenue) as total_revenue,
                countIf(event IN ({conversion_events_str})) as conversions
            FROM events 
            WHERE timestamp >= now() - interval {days} day
            AND (
                event IN ({conversion_events_str})
                OR properties.utm_source IS NOT NULL
            )
            GROUP BY person_id
        )
        SELECT 
            last_utm_source as utm_source,
            last_utm_campaign as utm_campaign,
            sum(conversions) as attributed_conversions,
            sum(total_revenue) as attributed_revenue,
            count() as unique_customers
        FROM last_touch_attribution
        WHERE last_utm_source IS NOT NULL
        GROUP BY last_utm_source, last_utm_campaign
        ORDER BY attributed_revenue DESC
        """
    
    elif model_type == 'linear':
        return f"""
        WITH touchpoint_data AS (
            SELECT 
                person_id,
                properties.utm_source as utm_source,
                properties.utm_campaign as utm_campaign,
                countIf(properties.utm_source IS NOT NULL) OVER (PARTITION BY person_id) as total_touchpoints,
                sum(properties.revenue) OVER (PARTITION BY person_id) as person_revenue,
                countIf(event IN ({conversion_events_str})) OVER (PARTITION BY person_id) as person_conversions
            FROM events 
            WHERE timestamp >= now() - interval {days} day
            AND (
                event IN ({conversion_events_str})
                OR properties.utm_source IS NOT NULL
            )
        )
        SELECT 
            utm_source,
            utm_campaign,
            sum(person_conversions / nullIf(total_touchpoints, 0)) as attributed_conversions,
            sum(person_revenue / nullIf(total_touchpoints, 0)) as attributed_revenue,
            count(DISTINCT person_id) as unique_customers
        FROM touchpoint_data
        WHERE utm_source IS NOT NULL
        GROUP BY utm_source, utm_campaign
        ORDER BY attributed_revenue DESC
        """
    
    else:
        raise ValueError(f"Unsupported attribution model: {model_type}")