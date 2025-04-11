from unittest.mock import patch
from django.test import TestCase, RequestFactory
from rest_framework.test import APIClient
from products.payments.backend.api import payments_products, StripeProductSerializer


class TestStripeProducts(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.client = APIClient()

        # Create mock Stripe response data
        self.mock_product = {
            "id": "prod_test123",
            "object": "product",
            "active": True,
            "name": "Test Product",
            "description": "Test description",
            "metadata": {},
        }

        self.mock_products_list = {
            "object": "list",
            "url": "/v1/products",
            "has_more": False,
            "data": [self.mock_product],
        }

    @patch("products.payments.backend.api.stripe.Product.list")
    def test_list_products(self, mock_list):
        """Test listing all products"""
        mock_list.return_value = self.mock_products_list

        request = self.factory.get("/payments/products/")
        response = payments_products(request)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, self.mock_products_list)
        mock_list.assert_called_once()

    @patch("products.payments.backend.api.stripe.Product.retrieve")
    def test_retrieve_product(self, mock_retrieve):
        """Test retrieving a specific product"""
        mock_retrieve.return_value = self.mock_product

        request = self.factory.get("/payments/products/prod_test123/")
        response = payments_products(request, product_id="prod_test123")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, self.mock_product)
        mock_retrieve.assert_called_once_with("prod_test123")

    @patch("products.payments.backend.api.stripe.Product.create")
    def test_create_product(self, mock_create):
        """Test creating a new product"""
        mock_create.return_value = self.mock_product

        product_data = {"name": "Test Product", "description": "Test description"}

        request = self.factory.post("/payments/products/", product_data, content_type="application/json")
        response = payments_products(request)

        self.assertEqual(response.status_code, 201)
        mock_create.assert_called_once()

    @patch("products.payments.backend.api.stripe.Product.modify")
    def test_update_product(self, mock_modify):
        """Test updating a product"""
        updated_product = dict(self.mock_product)
        updated_product["description"] = "Updated description"
        mock_modify.return_value = updated_product

        update_data = {"description": "Updated description"}

        request = self.factory.patch("/payments/products/prod_test123/", update_data, content_type="application/json")
        response = payments_products(request, product_id="prod_test123")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["description"], "Updated description")
        mock_modify.assert_called_once()

    @patch("products.payments.backend.api.stripe.Product.delete")
    def test_delete_product(self, mock_delete):
        """Test deleting a product"""
        mock_delete.return_value = {"id": "prod_test123", "deleted": True}

        request = self.factory.delete("/payments/products/prod_test123/")
        response = payments_products(request, product_id="prod_test123")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, {"id": "prod_test123", "deleted": True})
        mock_delete.assert_called_once_with("prod_test123")

    def test_serializer_validation(self):
        """Test product serializer validation"""
        # Valid data
        valid_data = {"name": "Test Product"}
        serializer = StripeProductSerializer(data=valid_data)
        self.assertTrue(serializer.is_valid())

        # Invalid data (missing required field)
        invalid_data = {"description": "No name provided"}
        serializer = StripeProductSerializer(data=invalid_data)
        self.assertFalse(serializer.is_valid())
