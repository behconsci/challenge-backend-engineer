"""Tests for the order mapper."""

from typing import Any

from portal.services.mapper import map_order


class TestMapOrderBasicFields:
    def test_order_number(self, raw_order_1001: dict[str, Any]) -> None:
        order = map_order(raw_order_1001)
        assert order.order_number == "RMA-1001"

    def test_email(self, raw_order_1001: dict[str, Any]) -> None:
        order = map_order(raw_order_1001)
        assert order.email == "alex@example.com"

    def test_recipient(self, raw_order_1001: dict[str, Any]) -> None:
        order = map_order(raw_order_1001)
        assert order.recipient == "Jane Doe"

    def test_dates_parsed(self, raw_order_1001: dict[str, Any]) -> None:
        order = map_order(raw_order_1001)
        assert order.order_date.year == 2025
        assert order.delivery_date.month == 12

    def test_article_count(self, raw_order_1001: dict[str, Any]) -> None:
        order = map_order(raw_order_1001)
        assert len(order.articles) == 3


class TestMapArticleBasicFields:
    def test_sku(self, raw_order_1001: dict[str, Any]) -> None:
        order = map_order(raw_order_1001)
        assert order.articles[0].sku == "TSHIRT-BLK-M"

    def test_name(self, raw_order_1001: dict[str, Any]) -> None:
        order = map_order(raw_order_1001)
        assert order.articles[0].name == "T-Shirt Black M"

    def test_price(self, raw_order_1001: dict[str, Any]) -> None:
        order = map_order(raw_order_1001)
        assert order.articles[0].price == 29.99

    def test_quantity(self, raw_order_1001: dict[str, Any]) -> None:
        order = map_order(raw_order_1001)
        assert order.articles[0].quantity == 2
        assert order.articles[0].quantity_returned == 0


class TestMapArticleMissingFields:
    # --- is_digital ---

    def test_is_digital_via_tag(self, raw_order_1001: dict[str, Any]) -> None:
        """Fixture uses requires_shipping=False + tag 'digital-delivery'."""
        order = map_order(raw_order_1001)
        ebook = order.articles[1]  # EBOOK-RETURNS
        assert ebook.is_digital is True

    def test_is_digital_via_explicit_key(self) -> None:
        """Raw JSON uses 'digital': true directly."""
        raw = {
            "order_number": "X-001",
            "email": "a@b.com",
            "order_date": "2025-01-01T00:00:00Z",
            "fulfillments": [{"delivered_at": "2025-01-05T00:00:00Z", "carrier": "dhl", "tracking_number": "T1"}],
            "articles": [{"sku": "DIG-01", "name": "Digital Good", "quantity": 1,
                          "quantity_returned": 0, "price": 9.99, "digital": True, "final_sale": False}],
        }
        order = map_order(raw)
        assert order.articles[0].is_digital is True

    def test_is_digital_false_for_physical_item(self, raw_order_1001: dict[str, Any]) -> None:
        order = map_order(raw_order_1001)
        tshirt = order.articles[0]  # TSHIRT-BLK-M
        assert tshirt.is_digital is False

    # --- is_final_sale ---

    def test_is_final_sale_via_tag(self, raw_order_1002: dict[str, Any]) -> None:
        """Fixture uses tag 'final-sale'."""
        order = map_order(raw_order_1002)
        shoes = order.articles[0]  # SHOES-CLR-42
        assert shoes.is_final_sale is True

    def test_is_final_sale_via_explicit_key(self) -> None:
        """Raw JSON uses 'final_sale': true directly."""
        raw = {
            "order_number": "X-002",
            "email": "a@b.com",
            "order_date": "2025-01-01T00:00:00Z",
            "fulfillments": [{"delivered_at": "2025-01-05T00:00:00Z", "carrier": "dhl", "tracking_number": "T1"}],
            "articles": [{"sku": "FS-01", "name": "Final Sale Item", "quantity": 1,
                          "quantity_returned": 0, "price": 19.99, "digital": False, "final_sale": True}],
        }
        order = map_order(raw)
        assert order.articles[0].is_final_sale is True

    def test_is_final_sale_false_for_regular_item(self, raw_order_1001: dict[str, Any]) -> None:
        order = map_order(raw_order_1001)
        tshirt = order.articles[0]  # TSHIRT-BLK-M
        assert tshirt.is_final_sale is False

    # --- category ---

    def test_category_from_product_type_apparel(self, raw_order_1001: dict[str, Any]) -> None:
        """Fixture uses product_type 'Apparel > T-Shirts' — maps to 'apparel'."""
        order = map_order(raw_order_1001)
        assert order.articles[0].category == "apparel"

    def test_category_from_product_type_digital(self, raw_order_1001: dict[str, Any]) -> None:
        """Fixture uses product_type 'Digital > Books' — maps to 'digital'."""
        order = map_order(raw_order_1001)
        assert order.articles[1].category == "digital"

    def test_category_from_explicit_key(self) -> None:
        """Raw JSON uses 'category': 'footwear' directly."""
        raw = {
            "order_number": "X-003",
            "email": "a@b.com",
            "order_date": "2025-01-01T00:00:00Z",
            "fulfillments": [{"delivered_at": "2025-01-05T00:00:00Z", "carrier": "dhl", "tracking_number": "T1"}],
            "articles": [{"sku": "SHOE-01", "name": "Sneaker", "quantity": 1,
                          "quantity_returned": 0, "price": 89.99, "category": "footwear",
                          "digital": False, "final_sale": False}],
        }
        order = map_order(raw)
        assert order.articles[0].category == "footwear"

    def test_category_explicit_key_takes_precedence_over_product_type(self) -> None:
        """When both keys are present, 'category' wins."""
        raw = {
            "order_number": "X-004",
            "email": "a@b.com",
            "order_date": "2025-01-01T00:00:00Z",
            "fulfillments": [{"delivered_at": "2025-01-05T00:00:00Z", "carrier": "dhl", "tracking_number": "T1"}],
            "articles": [{"sku": "MIX-01", "name": "Mixed", "quantity": 1,
                          "quantity_returned": 0, "price": 49.99, "category": "electronics",
                          "product_type": "Apparel > Jackets", "digital": False, "final_sale": False}],
        }
        order = map_order(raw)
        assert order.articles[0].category == "electronics"

    # --- return_window_days ---

    def test_return_window_days_mapped(self) -> None:
        raw = {
            "order_number": "X-005",
            "email": "a@b.com",
            "order_date": "2025-01-01T00:00:00Z",
            "return_window_days": 14,
            "fulfillments": [{"delivered_at": "2025-01-05T00:00:00Z", "carrier": "dhl", "tracking_number": "T1"}],
            "articles": [],
        }
        order = map_order(raw)
        assert order.return_window_days == 14

    def test_return_window_days_defaults_to_30(self, raw_order_1001: dict[str, Any]) -> None:
        order = map_order(raw_order_1001)
        assert order.return_window_days == 30
