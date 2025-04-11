from rest_framework.request import Request
from rest_framework import viewsets, serializers
from .models import PaymentTransaction
from rest_framework.response import Response
from typing import Any


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
