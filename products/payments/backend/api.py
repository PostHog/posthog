from rest_framework.request import Request
from rest_framework import viewsets, serializers, status
from .models import PaymentTransaction
from rest_framework.response import Response
from typing import Any
import logging
import stripe
from django.views.decorators.csrf import csrf_exempt

logger = logging.getLogger(__name__)

STRIPE_API_KEY = ""


class TransactionSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source="product.name", read_only=True)

    class Meta:
        model = PaymentTransaction
        fields = ["id", "team_id", "product_id", "product_name", "payload", "status", "date_created"]
        read_only_fields = fields


def list_transactions_response(transactions, page_size: int, page: int, total_count: int, context: dict) -> Response:
    """Helper function to format the transaction list response with pagination"""
    transaction_serializer = TransactionSerializer(transactions, context=context, many=True)

    return Response(
        {
            "results": transaction_serializer.data,
            "count": total_count,
            "next": None if (page * page_size) >= total_count else page + 1,
            "previous": None if page <= 1 else page - 1,
        }
    )


class TransactionViewSet(viewsets.GenericViewSet):
    serializer_class = TransactionSerializer
    queryset = PaymentTransaction.objects.none()  # Required for DRF
    DEFAULT_PAGE_SIZE = 100

    def get_queryset(self):
        return (
            PaymentTransaction.objects.filter(team_id=self.team.id).select_related("product").order_by("-date_created")
        )

    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        page_size = int(request.GET.get("page_size", self.DEFAULT_PAGE_SIZE))
        page = int(request.GET.get("page", 1))

        queryset = self.get_queryset()
        total_count = queryset.count()

        start = (page - 1) * page_size
        end = start + page_size

        transactions = queryset[start:end]

        return list_transactions_response(
            transactions=transactions,
            page_size=page_size,
            page=page,
            total_count=total_count,
            context=self.get_serializer_context(),
        )


class StripeProductSerializer(serializers.Serializer):
    """Serializer for Stripe product operations"""

    name = serializers.CharField(required=True)
    active = serializers.BooleanField(required=False)
    description = serializers.CharField(required=False, allow_blank=True)
    id = serializers.CharField(required=False)  # Custom ID (optional)
    metadata = serializers.DictField(required=False)
    tax_code = serializers.CharField(required=False, allow_null=True)

    # Additional optional fields
    images = serializers.ListField(child=serializers.CharField(), required=False)
    shippable = serializers.BooleanField(required=False)
    statement_descriptor = serializers.CharField(required=False, allow_blank=True)
    unit_label = serializers.CharField(required=False, allow_blank=True)
    url = serializers.CharField(required=False, allow_blank=True)


class ProductViewSet(viewsets.ViewSet):
    """ViewSet for handling Stripe product operations"""

    def _initialize_stripe(self):
        """Initialize Stripe with the API key from settings"""
        stripe.api_key = STRIPE_API_KEY

    def _handle_stripe_error(self, e: stripe.error.StripeError) -> Response:
        """Handle Stripe errors and return appropriate responses"""
        logger.error(f"Stripe error: {str(e)}")
        return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    def list(self, request: Request, parent_lookup_project_id=None) -> Response:
        """
        List all products from Stripe
        GET /payments/products/
        """
        self._initialize_stripe()

        try:
            params = {}

            # Handle pagination params
            if "limit" in request.query_params:
                params["limit"] = int(request.query_params.get("limit"))

            if "starting_after" in request.query_params:
                params["starting_after"] = request.query_params.get("starting_after")

            if "ending_before" in request.query_params:
                params["ending_before"] = request.query_params.get("ending_before")

            # Handle filtering params
            if "active" in request.query_params:
                params["active"] = request.query_params.get("active").lower() == "true"

            products = stripe.Product.list(**params)
            return Response(products)

        except stripe.error.StripeError as e:
            return self._handle_stripe_error(e)

    def retrieve(self, request: Request, pk=None) -> Response:
        """
        Retrieve a specific product from Stripe
        GET /payments/products/:id
        """
        if not pk:
            return Response({"error": "Product ID is required"}, status=status.HTTP_400_BAD_REQUEST)

        self._initialize_stripe()

        try:
            product = stripe.Product.retrieve(pk)
            return Response(product)
        except stripe.error.StripeError as e:
            return self._handle_stripe_error(e)

    def create(self, request: Request) -> Response:
        """
        Create a new product in Stripe
        POST /payments/products/
        """
        serializer = StripeProductSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        self._initialize_stripe()

        try:
            product = stripe.Product.create(**serializer.validated_data)
            return Response(product, status=status.HTTP_201_CREATED)
        except stripe.error.StripeError as e:
            return self._handle_stripe_error(e)

    def partial_update(self, request: Request, pk=None) -> Response:
        """
        Update an existing product in Stripe
        PATCH /payments/products/:id
        """
        if not pk:
            return Response({"error": "Product ID is required"}, status=status.HTTP_400_BAD_REQUEST)

        serializer = StripeProductSerializer(data=request.data, partial=True)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        self._initialize_stripe()

        try:
            product = stripe.Product.modify(pk, **serializer.validated_data)
            return Response(product)
        except stripe.error.StripeError as e:
            return self._handle_stripe_error(e)

    def destroy(self, request: Request, pk=None) -> Response:
        """
        Delete a product from Stripe
        DELETE /payments/products/:id
        """
        if not pk:
            return Response({"error": "Product ID is required"}, status=status.HTTP_400_BAD_REQUEST)

        self._initialize_stripe()

        try:
            deleted = stripe.Product.delete(pk)
            return Response(deleted)
        except stripe.error.StripeError as e:
            return self._handle_stripe_error(e)


# Direct API routes for payments/products
@csrf_exempt
def payments_products(request: Request, product_id=None):
    """
    Handle RESTful operations on Stripe products
    - GET /payments/products/ - List all products
    - GET /payments/products/:id - Get a specific product
    - POST /payments/products/ - Create a new product
    - PATCH /payments/products/:id - Update a product
    - DELETE /payments/products/:id - Delete a product
    """
    product_view = ProductViewSet()

    if request.method == "GET":
        if product_id:
            # Get specific product
            return product_view.retrieve(request, pk=product_id)
        else:
            # List all products
            return product_view.list(request)

    elif request.method == "POST":
        # Create a new product
        return product_view.create(request)

    elif request.method == "PATCH":
        # Update a product
        if not product_id:
            return Response({"error": "Product ID is required for updates"}, status=status.HTTP_400_BAD_REQUEST)
        return product_view.partial_update(request, pk=product_id)

    elif request.method == "DELETE":
        # Delete a product
        if not product_id:
            return Response({"error": "Product ID is required for deletion"}, status=status.HTTP_400_BAD_REQUEST)
        return product_view.destroy(request, pk=product_id)

    # Method not allowed
    return Response({"error": f"Method {request.method} not allowed"}, status=status.HTTP_405_METHOD_NOT_ALLOWED)


class StripePriceSerializer(serializers.Serializer):
    """Serializer for Stripe price operations"""

    currency = serializers.CharField(required=True)
    unit_amount = serializers.IntegerField(required=True)
    active = serializers.BooleanField(required=False)
    metadata = serializers.DictField(required=False)
    nickname = serializers.CharField(required=False, allow_blank=True)
    product = serializers.CharField(required=True)
    recurring = serializers.DictField(required=False)
    tax_behavior = serializers.CharField(required=False)


class PriceViewSet(viewsets.ViewSet):
    """ViewSet for handling Stripe price operations"""

    def _initialize_stripe(self):
        """Initialize Stripe with the API key from settings"""
        stripe.api_key = STRIPE_API_KEY

    def _handle_stripe_error(self, e: stripe.error.StripeError) -> Response:
        """Handle Stripe errors and return appropriate responses"""
        logger.error(f"Stripe error: {str(e)}")
        return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    def list(self, request: Request, parent_lookup_project_id=None) -> Response:
        """
        List all prices from Stripe
        GET /payments/prices/
        """
        self._initialize_stripe()

        try:
            params = {}

            # Handle pagination params
            if "limit" in request.query_params:
                params["limit"] = int(request.query_params.get("limit"))

            if "starting_after" in request.query_params:
                params["starting_after"] = request.query_params.get("starting_after")

            if "ending_before" in request.query_params:
                params["ending_before"] = request.query_params.get("ending_before")

            prices = stripe.Price.list(**params)
            return Response(prices)

        except stripe.error.StripeError as e:
            return self._handle_stripe_error(e)

    def retrieve(self, request: Request, pk=None) -> Response:
        """
        Retrieve a specific price from Stripe
        GET /payments/prices/:id
        """
        if not pk:
            return Response({"error": "Price ID is required"}, status=status.HTTP_400_BAD_REQUEST)

        self._initialize_stripe()

        try:
            price = stripe.Price.retrieve(pk)
            return Response(price)
        except stripe.error.StripeError as e:
            return self._handle_stripe_error(e)

    def create(self, request: Request) -> Response:
        """
        Create a new price in Stripe
        POST /payments/prices/
        """
        serializer = StripePriceSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        self._initialize_stripe()

        try:
            price = stripe.Price.create(**serializer.validated_data)
            return Response(price, status=status.HTTP_201_CREATED)
        except stripe.error.StripeError as e:
            return self._handle_stripe_error(e)

    def partial_update(self, request: Request, pk=None) -> Response:
        """
        Update an existing price in Stripe
        PATCH /payments/prices/:id
        """
        if not pk:
            return Response({"error": "Price ID is required"}, status=status.HTTP_400_BAD_REQUEST)

        serializer = StripePriceSerializer(data=request.data, partial=True)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        self._initialize_stripe()

        try:
            price = stripe.Price.modify(pk, **serializer.validated_data)
            return Response(price)
        except stripe.error.StripeError as e:
            return self._handle_stripe_error(e)

    def destroy(self, request: Request, pk=None) -> Response:
        """
        Delete a price from Stripe
        DELETE /payments/prices/:id
        """
        if not pk:
            return Response({"error": "Price ID is required"}, status=status.HTTP_400_BAD_REQUEST)

        self._initialize_stripe()

        try:
            deleted = stripe.Price.delete(pk)
            return Response(deleted)
        except stripe.error.StripeError as e:
            return self._handle_stripe_error(e)


# Direct API routes for payments/prices
@csrf_exempt
def payments_prices(request: Request, price_id=None):
    """
    Handle RESTful operations on Stripe prices
    - GET /payments/prices/ - List all prices
    - GET /payments/prices/:id - Get a specific price
    - POST /payments/prices/ - Create a new price
    - PATCH /payments/prices/:id - Update a price
    - DELETE /payments/prices/:id - Delete a price
    """
    price_view = PriceViewSet()

    if request.method == "GET":
        if price_id:
            # Get specific price
            return price_view.retrieve(request, pk=price_id)
        else:
            # List all prices
            return price_view.list(request)

    elif request.method == "POST":
        # Create a new price
        return price_view.create(request)

    elif request.method == "PATCH":
        # Update a price
        if not price_id:
            return Response({"error": "Price ID is required for updates"}, status=status.HTTP_400_BAD_REQUEST)
        return price_view.partial_update(request, pk=price_id)

    elif request.method == "DELETE":
        # Delete a price
        if not price_id:
            return Response({"error": "Price ID is required for deletion"}, status=status.HTTP_400_BAD_REQUEST)
        return price_view.destroy(request, pk=price_id)

    # Method not allowed
    return Response({"error": f"Method {request.method} not allowed"}, status=status.HTTP_405_METHOD_NOT_ALLOWED)


class StripeBalanceTransactionSerializer(serializers.Serializer):
    """Serializer for Stripe balance transaction operations"""

    currency = serializers.CharField(required=True)
    amount = serializers.IntegerField(required=True)
    description = serializers.CharField(required=False, allow_blank=True)
    metadata = serializers.DictField(required=False)


class BalanceTransactionViewSet(viewsets.ViewSet):
    """ViewSet for handling Stripe balance transaction operations"""

    def _initialize_stripe(self):
        """Initialize Stripe with the API key from settings"""
        stripe.api_key = STRIPE_API_KEY

    def _handle_stripe_error(self, e: stripe.error.StripeError) -> Response:
        """Handle Stripe errors and return appropriate responses"""
        logger.error(f"Stripe error: {str(e)}")
        return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    def list(self, request: Request, parent_lookup_project_id=None) -> Response:
        """
        List all balance transactions from Stripe
        GET /payments/balance_transactions/
        """
        self._initialize_stripe()

        try:
            params = {}

            # Handle pagination params
            if "limit" in request.query_params:
                params["limit"] = int(request.query_params.get("limit"))

            if "starting_after" in request.query_params:
                params["starting_after"] = request.query_params.get("starting_after")

            if "ending_before" in request.query_params:
                params["ending_before"] = request.query_params.get("ending_before")

            balance_transactions = stripe.BalanceTransaction.list(**params)
            return Response(balance_transactions)

        except stripe.error.StripeError as e:
            return self._handle_stripe_error(e)

    def retrieve(self, request: Request, pk=None) -> Response:
        """
        Retrieve a specific balance transaction from Stripe
        GET /payments/balance_transactions/:id
        """
        if not pk:
            return Response({"error": "Transaction ID is required"}, status=status.HTTP_400_BAD_REQUEST)

        self._initialize_stripe()

        try:
            balance_transaction = stripe.BalanceTransaction.retrieve(pk)
            return Response(balance_transaction)
        except stripe.error.StripeError as e:
            return self._handle_stripe_error(e)


# Direct API routes for payments/balance_transactions
@csrf_exempt
def payments_balance_transactions(request: Request, transaction_id=None):
    """
    Handle RESTful operations on Stripe balance transactions
    - GET /payments/balance_transactions/ - List all transactions
    - GET /payments/balance_transactions/:id - Get a specific transaction
    """
    transaction_view = BalanceTransactionViewSet()

    if request.method == "GET":
        if transaction_id:
            # Get specific transaction
            return transaction_view.retrieve(request, pk=transaction_id)
        else:
            # List all transactions
            return transaction_view.list(request)

    # Method not allowed
    return Response({"error": f"Method {request.method} not allowed"}, status=status.HTTP_405_METHOD_NOT_ALLOWED)
