"""
Revenue Tracking and Webhook Integration for Marketing Analytics

This module handles revenue tracking from various payment gateways and provides
webhook endpoints to capture conversion data from external sources.
"""

import datetime
import hashlib
import hmac
import json
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from django.conf import settings
from django.http import HttpRequest, HttpResponse, HttpResponseBadRequest
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from posthog.api.utils import posthog_exception_handler
from posthog.models import Event, Team


@dataclass
class RevenueEvent:
    """Structured revenue event data"""
    transaction_id: str
    customer_id: str | None
    amount: Decimal
    currency: str
    gateway: str
    timestamp: datetime.datetime
    properties: dict[str, Any]
    utm_source: str | None = None
    utm_campaign: str | None = None
    utm_medium: str | None = None


class WebhookSignatureValidator:
    """Validates webhook signatures from different payment gateways"""
    
    @staticmethod
    def validate_stripe_signature(payload: bytes, signature: str, webhook_secret: str) -> bool:
        """Validate Stripe webhook signature"""
        try:
            elements = signature.split(',')
            timestamp = None
            signature_hash = None
            
            for element in elements:
                if element.startswith('t='):
                    timestamp = element[2:]
                elif element.startswith('v1='):
                    signature_hash = element[3:]
            
            if not timestamp or not signature_hash:
                return False
            
            # Create expected signature
            signed_payload = f"{timestamp}.{payload.decode('utf-8')}"
            expected_signature = hmac.new(
                webhook_secret.encode('utf-8'),
                signed_payload.encode('utf-8'),
                hashlib.sha256
            ).hexdigest()
            
            return hmac.compare_digest(signature_hash, expected_signature)
        except Exception:
            return False
    
    @staticmethod
    def validate_paypal_signature(payload: bytes, signature: str, webhook_id: str) -> bool:
        """Validate PayPal webhook signature"""
        # PayPal webhook validation would be implemented here
        # This is a simplified version
        return True  # Placeholder
    
    @staticmethod
    def validate_square_signature(payload: bytes, signature: str, webhook_secret: str) -> bool:
        """Validate Square webhook signature"""
        try:
            expected_signature = hmac.new(
                webhook_secret.encode('utf-8'),
                payload,
                hashlib.sha256
            ).hexdigest()
            
            return hmac.compare_digest(signature, expected_signature)
        except Exception:
            return False


class RevenueEventProcessor:
    """Processes revenue events and creates PostHog events"""
    
    def __init__(self, team: Team):
        self.team = team
    
    def process_revenue_event(self, revenue_event: RevenueEvent) -> Event:
        """Create a PostHog event from a revenue event"""
        
        properties = {
            'transaction_id': revenue_event.transaction_id,
            'revenue': float(revenue_event.amount),
            'currency': revenue_event.currency,
            'payment_gateway': revenue_event.gateway,
            **revenue_event.properties
        }
        
        # Add UTM parameters if available
        if revenue_event.utm_source:
            properties['utm_source'] = revenue_event.utm_source
        if revenue_event.utm_campaign:
            properties['utm_campaign'] = revenue_event.utm_campaign
        if revenue_event.utm_medium:
            properties['utm_medium'] = revenue_event.utm_medium
        
        # Create the event
        event = Event.objects.create(
            team=self.team,
            event='purchase',
            distinct_id=revenue_event.customer_id or revenue_event.transaction_id,
            properties=properties,
            timestamp=revenue_event.timestamp,
            person_id=revenue_event.customer_id
        )
        
        return event
    
    def deduplicate_revenue_events(self, transaction_id: str, days: int = 7) -> bool:
        """Check if a transaction has already been processed to prevent duplicates"""
        
        cutoff_date = datetime.datetime.now() - datetime.timedelta(days=days)
        
        existing_event = Event.objects.filter(
            team=self.team,
            properties__transaction_id=transaction_id,
            timestamp__gte=cutoff_date
        ).first()
        
        return existing_event is not None


class StripeWebhookHandler:
    """Handles Stripe webhook events"""
    
    def __init__(self, team: Team):
        self.team = team
        self.processor = RevenueEventProcessor(team)
    
    def handle_payment_intent_succeeded(self, event_data: dict[str, Any]) -> Event | None:
        """Handle successful payment intent from Stripe"""
        
        payment_intent = event_data.get('data', {}).get('object', {})
        
        if not payment_intent:
            return None
        
        transaction_id = payment_intent.get('id')
        amount = Decimal(payment_intent.get('amount', 0)) / 100  # Convert from cents
        currency = payment_intent.get('currency', 'usd').upper()
        customer_id = payment_intent.get('customer')
        
        # Extract metadata for UTM tracking
        metadata = payment_intent.get('metadata', {})
        
        revenue_event = RevenueEvent(
            transaction_id=transaction_id,
            customer_id=customer_id,
            amount=amount,
            currency=currency,
            gateway='stripe',
            timestamp=datetime.datetime.now(),
            properties={
                'stripe_payment_method': payment_intent.get('payment_method'),
                'stripe_status': payment_intent.get('status'),
                **metadata
            },
            utm_source=metadata.get('utm_source'),
            utm_campaign=metadata.get('utm_campaign'),
            utm_medium=metadata.get('utm_medium')
        )
        
        # Check for duplicates
        if self.processor.deduplicate_revenue_events(transaction_id):
            return None
        
        return self.processor.process_revenue_event(revenue_event)
    
    def handle_invoice_payment_succeeded(self, event_data: dict[str, Any]) -> Event | None:
        """Handle successful subscription payment from Stripe"""
        
        invoice = event_data.get('data', {}).get('object', {})
        
        if not invoice:
            return None
        
        transaction_id = invoice.get('id')
        amount = Decimal(invoice.get('amount_paid', 0)) / 100
        currency = invoice.get('currency', 'usd').upper()
        customer_id = invoice.get('customer')
        subscription_id = invoice.get('subscription')
        
        revenue_event = RevenueEvent(
            transaction_id=transaction_id,
            customer_id=customer_id,
            amount=amount,
            currency=currency,
            gateway='stripe',
            timestamp=datetime.datetime.now(),
            properties={
                'subscription_id': subscription_id,
                'billing_reason': invoice.get('billing_reason'),
                'invoice_status': invoice.get('status'),
                'period_start': invoice.get('period_start'),
                'period_end': invoice.get('period_end'),
            }
        )
        
        if self.processor.deduplicate_revenue_events(transaction_id):
            return None
        
        return self.processor.process_revenue_event(revenue_event)


class PayPalWebhookHandler:
    """Handles PayPal webhook events"""
    
    def __init__(self, team: Team):
        self.team = team
        self.processor = RevenueEventProcessor(team)
    
    def handle_payment_capture_completed(self, event_data: dict[str, Any]) -> Event | None:
        """Handle completed payment capture from PayPal"""
        
        resource = event_data.get('resource', {})
        
        if not resource:
            return None
        
        transaction_id = resource.get('id')
        amount_data = resource.get('amount', {})
        amount = Decimal(amount_data.get('value', 0))
        currency = amount_data.get('currency_code', 'USD')
        
        # Extract payer information
        payer = resource.get('payer', {})
        payer_id = payer.get('payer_id')
        
        revenue_event = RevenueEvent(
            transaction_id=transaction_id,
            customer_id=payer_id,
            amount=amount,
            currency=currency,
            gateway='paypal',
            timestamp=datetime.datetime.now(),
            properties={
                'paypal_status': resource.get('status'),
                'paypal_payer_email': payer.get('email_address'),
                'paypal_payer_name': payer.get('name', {}).get('given_name'),
            }
        )
        
        if self.processor.deduplicate_revenue_events(transaction_id):
            return None
        
        return self.processor.process_revenue_event(revenue_event)


# Django Views for Webhook Endpoints

@csrf_exempt
@require_http_methods(["POST"])
@posthog_exception_handler
def stripe_webhook(request: HttpRequest) -> HttpResponse:
    """Stripe webhook endpoint"""
    
    # Get team from request or headers
    team_id = request.headers.get('X-PostHog-Team-Id')
    if not team_id:
        return HttpResponseBadRequest("Missing team ID")
    
    try:
        team = Team.objects.get(id=team_id)
    except Team.DoesNotExist:
        return HttpResponseBadRequest("Invalid team ID")
    
    # Validate signature
    signature = request.headers.get('stripe-signature', '')
    webhook_secret = getattr(settings, 'STRIPE_WEBHOOK_SECRET', '')
    
    if not WebhookSignatureValidator.validate_stripe_signature(
        request.body, signature, webhook_secret
    ):
        return HttpResponseBadRequest("Invalid signature")
    
    try:
        event_data = json.loads(request.body)
        event_type = event_data.get('type')
        
        handler = StripeWebhookHandler(team)
        
        if event_type == 'payment_intent.succeeded':
            event = handler.handle_payment_intent_succeeded(event_data)
        elif event_type == 'invoice.payment_succeeded':
            event = handler.handle_invoice_payment_succeeded(event_data)
        else:
            # Event type not handled
            return HttpResponse(status=200)
        
        if event:
            return HttpResponse(f"Event processed: {event.id}", status=200)
        else:
            return HttpResponse("Event skipped (duplicate)", status=200)
        
    except Exception as e:
        return HttpResponseBadRequest(f"Error processing webhook: {str(e)}")


@csrf_exempt
@require_http_methods(["POST"])
@posthog_exception_handler
def paypal_webhook(request: HttpRequest) -> HttpResponse:
    """PayPal webhook endpoint"""
    
    team_id = request.headers.get('X-PostHog-Team-Id')
    if not team_id:
        return HttpResponseBadRequest("Missing team ID")
    
    try:
        team = Team.objects.get(id=team_id)
    except Team.DoesNotExist:
        return HttpResponseBadRequest("Invalid team ID")
    
    try:
        event_data = json.loads(request.body)
        event_type = event_data.get('event_type')
        
        handler = PayPalWebhookHandler(team)
        
        if event_type == 'PAYMENT.CAPTURE.COMPLETED':
            event = handler.handle_payment_capture_completed(event_data)
        else:
            return HttpResponse(status=200)
        
        if event:
            return HttpResponse(f"Event processed: {event.id}", status=200)
        else:
            return HttpResponse("Event skipped (duplicate)", status=200)
        
    except Exception as e:
        return HttpResponseBadRequest(f"Error processing webhook: {str(e)}")


@csrf_exempt
@require_http_methods(["POST"])
@posthog_exception_handler
def generic_revenue_webhook(request: HttpRequest) -> HttpResponse:
    """Generic webhook endpoint for custom revenue tracking"""
    
    team_id = request.headers.get('X-PostHog-Team-Id')
    if not team_id:
        return HttpResponseBadRequest("Missing team ID")
    
    try:
        team = Team.objects.get(id=team_id)
    except Team.DoesNotExist:
        return HttpResponseBadRequest("Invalid team ID")
    
    try:
        data = json.loads(request.body)
        
        # Extract required fields
        transaction_id = data.get('transaction_id')
        amount = Decimal(str(data.get('amount', 0)))
        currency = data.get('currency', 'USD')
        customer_id = data.get('customer_id')
        gateway = data.get('gateway', 'custom')
        
        if not transaction_id or amount <= 0:
            return HttpResponseBadRequest("Missing required fields")
        
        revenue_event = RevenueEvent(
            transaction_id=transaction_id,
            customer_id=customer_id,
            amount=amount,
            currency=currency,
            gateway=gateway,
            timestamp=datetime.datetime.now(),
            properties=data.get('properties', {}),
            utm_source=data.get('utm_source'),
            utm_campaign=data.get('utm_campaign'),
            utm_medium=data.get('utm_medium')
        )
        
        processor = RevenueEventProcessor(team)
        
        if processor.deduplicate_revenue_events(transaction_id):
            return HttpResponse("Event skipped (duplicate)", status=200)
        
        event = processor.process_revenue_event(revenue_event)
        return HttpResponse(f"Event processed: {event.id}", status=200)
        
    except Exception as e:
        return HttpResponseBadRequest(f"Error processing webhook: {str(e)}")


def generate_webhook_urls(team_id: int) -> dict[str, str]:
    """Generate webhook URLs for a team"""
    
    base_url = getattr(settings, 'SITE_URL', 'https://app.posthog.com')
    
    return {
        'stripe': f"{base_url}/webhooks/revenue/stripe",
        'paypal': f"{base_url}/webhooks/revenue/paypal", 
        'generic': f"{base_url}/webhooks/revenue/generic",
        'headers': {
            'X-PostHog-Team-Id': str(team_id)
        }
    }