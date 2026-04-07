"""Tests for the eligibility engine.

This is a starting point — not exhaustive.  You are expected to add tests
that cover your rules and edge cases.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import TypedDict, Unpack

from portal.services.eligibility import evaluate_eligibility
from portal.types import Article, Order


class _ArticleData(TypedDict):
    sku: str
    name: str
    quantity: int
    quantity_returned: int
    price: float
    is_digital: bool
    is_final_sale: bool
    category: str


class _ArticleOverrides(TypedDict, total=False):
    sku: str
    name: str
    quantity: int
    quantity_returned: int
    price: float
    is_digital: bool
    is_final_sale: bool
    category: str


def _make_order(
    articles: list[Article],
    delivery_date: datetime | None = None,
    return_window_days: int = 30,
) -> Order:
    return Order(
        order_number="TEST-001",
        email="test@example.com",
        recipient="Test User",
        zip="12345",
        street="Test Street 1",
        city="Testville",
        order_date=datetime(2025, 12, 1, 10, 0),
        delivery_date=delivery_date or datetime(2025, 12, 5, 14, 0),
        return_window_days=return_window_days,
        articles=articles,
    )


def _make_article(**overrides: Unpack[_ArticleOverrides]) -> Article:
    defaults: _ArticleData = {
        "sku": "TEST-SKU",
        "name": "Test Article",
        "quantity": 1,
        "quantity_returned": 0,
        "price": 19.99,
        "is_digital": False,
        "is_final_sale": False,
        "category": "general",
    }
    defaults.update(overrides)
    return Article(**defaults)


class TestNotYetDelivered:
    def test_future_delivery_is_not_returnable(self) -> None:
        order = _make_order(
            delivery_date=datetime.now() + timedelta(days=3),
            articles=[_make_article()],
        )
        results = evaluate_eligibility(order)
        assert results[0].returnable is False

    def test_future_delivery_matches_correct_rule(self) -> None:
        order = _make_order(
            delivery_date=datetime.now() + timedelta(days=3),
            articles=[_make_article()],
        )
        results = evaluate_eligibility(order)
        assert results[0].matched_rule == "not_yet_delivered"

    def test_future_delivery_beats_digital_rule(self) -> None:
        """not_yet_delivered (110) > digital_items (100)."""
        order = _make_order(
            delivery_date=datetime.now() + timedelta(days=1),
            articles=[_make_article(is_digital=True)],
        )
        results = evaluate_eligibility(order)
        assert results[0].matched_rule == "not_yet_delivered"

    def test_delivered_today_is_not_blocked(self) -> None:
        order = _make_order(
            delivery_date=datetime.now(),
            articles=[_make_article()],
        )
        results = evaluate_eligibility(order)
        assert results[0].matched_rule != "not_yet_delivered"


class TestClearanceItems:
    def test_clearance_category_is_not_returnable(self) -> None:
        order = _make_order(
            delivery_date=datetime.now() - timedelta(days=5),
            articles=[_make_article(category="clearance")],
        )
        results = evaluate_eligibility(order)
        assert results[0].returnable is False

    def test_clearance_matches_correct_rule(self) -> None:
        order = _make_order(
            delivery_date=datetime.now() - timedelta(days=5),
            articles=[_make_article(category="clearance")],
        )
        results = evaluate_eligibility(order)
        assert results[0].matched_rule == "clearance"

    def test_clearance_beats_already_returned(self) -> None:
        """clearance (85) > already_fully_returned (80)."""
        order = _make_order(
            delivery_date=datetime.now() - timedelta(days=5),
            articles=[_make_article(category="clearance", quantity=1, quantity_returned=1)],
        )
        results = evaluate_eligibility(order)
        assert results[0].matched_rule == "clearance"

    def test_non_clearance_category_not_blocked(self) -> None:
        order = _make_order(
            delivery_date=datetime.now() - timedelta(days=5),
            articles=[_make_article(category="apparel")],
        )
        results = evaluate_eligibility(order)
        assert results[0].matched_rule != "clearance"


class TestDigitalItems:
    """Digital items should not be returnable."""

    def test_digital_item_is_not_returnable(self) -> None:
        order = _make_order(
            articles=[
                _make_article(sku="EBOOK-01", name="E-Book", is_digital=True),
            ]
        )
        results = evaluate_eligibility(order)
        assert results[0].returnable is False


class TestAlreadyReturned:
    """Fully returned items should not be returnable."""

    def test_fully_returned_is_not_returnable(self) -> None:
        order = _make_order(
            articles=[
                _make_article(quantity=1, quantity_returned=1),
            ]
        )
        results = evaluate_eligibility(order)
        assert results[0].returnable is False

    def test_partially_returned_is_still_returnable(self) -> None:
        """An item with remaining quantity should still be returnable."""
        order = _make_order(
            delivery_date=datetime.now() - timedelta(days=5),
            articles=[_make_article(quantity=3, quantity_returned=1)],
        )
        results = evaluate_eligibility(order)
        assert results[0].returnable is True


class TestReturnWindow:
    """Items past the return window should not be returnable."""

    def test_expired_window_is_not_returnable(self) -> None:
        """Delivery 100 days ago — clearly outside any reasonable window."""
        order = _make_order(
            delivery_date=datetime.now() - timedelta(days=100),
            articles=[_make_article()],
        )
        results = evaluate_eligibility(order)
        assert results[0].returnable is False

    def test_recent_delivery_is_returnable(self) -> None:
        """Delivery 5 days ago — well within a typical return window."""
        order = _make_order(
            delivery_date=datetime.now() - timedelta(days=5),
            articles=[_make_article()],
        )
        results = evaluate_eligibility(order)
        assert results[0].returnable is True


class TestRegularItem:
    """A regular, non-digital, non-final-sale item within the return window
    should be returnable."""

    def test_regular_item_is_returnable(self) -> None:
        order = _make_order(
            delivery_date=datetime.now() - timedelta(days=5),
            articles=[_make_article()],
        )
        results = evaluate_eligibility(order)
        assert results[0].returnable is True

    def test_regular_item_matches_within_return_window_rule(self) -> None:
        order = _make_order(
            delivery_date=datetime.now() - timedelta(days=5),
            articles=[_make_article()],
        )
        results = evaluate_eligibility(order)
        assert results[0].matched_rule == "within_return_window"

    def test_returnable_item_has_empty_reason(self) -> None:
        order = _make_order(
            delivery_date=datetime.now() - timedelta(days=5),
            articles=[_make_article()],
        )
        results = evaluate_eligibility(order)
        assert results[0].reason == ""


class TestFinalSaleItems:
    def test_final_sale_item_is_not_returnable(self) -> None:
        order = _make_order(
            delivery_date=datetime.now() - timedelta(days=5),
            articles=[_make_article(is_final_sale=True)],
        )
        results = evaluate_eligibility(order)
        assert results[0].returnable is False

    def test_final_sale_matches_correct_rule(self) -> None:
        order = _make_order(
            delivery_date=datetime.now() - timedelta(days=5),
            articles=[_make_article(is_final_sale=True)],
        )
        results = evaluate_eligibility(order)
        assert results[0].matched_rule == "final_sale"

    def test_final_sale_reason_text(self) -> None:
        order = _make_order(
            delivery_date=datetime.now() - timedelta(days=5),
            articles=[_make_article(is_final_sale=True)],
        )
        results = evaluate_eligibility(order)
        assert "final sale" in results[0].reason.lower()


class TestPriorityOrdering:
    """Higher-priority rules must win when multiple conditions match."""

    def test_digital_beats_final_sale(self) -> None:
        """digital_items (priority 100) > final_sale (priority 90)."""
        order = _make_order(
            delivery_date=datetime.now() - timedelta(days=5),
            articles=[_make_article(is_digital=True, is_final_sale=True)],
        )
        results = evaluate_eligibility(order)
        assert results[0].matched_rule == "digital_items"

    def test_digital_beats_expired_window(self) -> None:
        """digital_items (priority 100) > return_window_expired (priority 70)."""
        order = _make_order(
            delivery_date=datetime.now() - timedelta(days=200),
            articles=[_make_article(is_digital=True)],
        )
        results = evaluate_eligibility(order)
        assert results[0].matched_rule == "digital_items"

    def test_fully_returned_beats_expired_window(self) -> None:
        """already_fully_returned (priority 80) > return_window_expired (priority 70)."""
        order = _make_order(
            delivery_date=datetime.now() - timedelta(days=200),
            articles=[_make_article(quantity=1, quantity_returned=1)],
        )
        results = evaluate_eligibility(order)
        assert results[0].matched_rule == "already_fully_returned"


class TestReturnWindowReason:
    def test_expired_reason_includes_days_since_delivery(self) -> None:
        order = _make_order(
            delivery_date=datetime.now() - timedelta(days=100),
            articles=[_make_article()],
        )
        results = evaluate_eligibility(order)
        assert "100" in results[0].reason

    def test_expired_reason_includes_window_days(self) -> None:
        order = _make_order(
            delivery_date=datetime.now() - timedelta(days=100),
            articles=[_make_article()],
        )
        results = evaluate_eligibility(order)
        # Default return_window_days is 30
        assert "30" in results[0].reason

    def test_custom_return_window_respected(self) -> None:
        order = _make_order(
            delivery_date=datetime.now() - timedelta(days=20),
            articles=[_make_article()],
            return_window_days=14,
        )
        results = evaluate_eligibility(order)
        assert results[0].returnable is False
        assert results[0].matched_rule == "return_window_expired"

    def test_item_on_boundary_day_is_returnable(self) -> None:
        """Delivered exactly return_window_days ago should still be allowed."""
        order = _make_order(
            delivery_date=datetime.now() - timedelta(days=30),
            articles=[_make_article()],
            return_window_days=30,
        )
        results = evaluate_eligibility(order)
        assert results[0].returnable is True


class TestCategoryReturnWindows:
    """Per-category windows override the order-level default."""

    def test_electronics_expired_at_15_days(self) -> None:
        order = _make_order(
            delivery_date=datetime.now() - timedelta(days=15),
            articles=[_make_article(category="electronics")],
        )
        results = evaluate_eligibility(order)
        assert results[0].returnable is False
        assert results[0].matched_rule == "electronics_window_expired"

    def test_electronics_valid_at_14_days(self) -> None:
        order = _make_order(
            delivery_date=datetime.now() - timedelta(days=14),
            articles=[_make_article(category="electronics")],
        )
        results = evaluate_eligibility(order)
        assert results[0].returnable is True
        assert results[0].matched_rule == "electronics_within_window"

    def test_apparel_expired_at_31_days(self) -> None:
        order = _make_order(
            delivery_date=datetime.now() - timedelta(days=31),
            articles=[_make_article(category="apparel")],
        )
        results = evaluate_eligibility(order)
        assert results[0].returnable is False
        assert results[0].matched_rule == "apparel_window_expired"

    def test_apparel_valid_at_30_days(self) -> None:
        order = _make_order(
            delivery_date=datetime.now() - timedelta(days=30),
            articles=[_make_article(category="apparel")],
        )
        results = evaluate_eligibility(order)
        assert results[0].returnable is True
        assert results[0].matched_rule == "apparel_within_window"

    def test_footwear_expired_at_61_days(self) -> None:
        order = _make_order(
            delivery_date=datetime.now() - timedelta(days=61),
            articles=[_make_article(category="footwear")],
        )
        results = evaluate_eligibility(order)
        assert results[0].returnable is False
        assert results[0].matched_rule == "footwear_window_expired"

    def test_footwear_valid_at_60_days(self) -> None:
        order = _make_order(
            delivery_date=datetime.now() - timedelta(days=60),
            articles=[_make_article(category="footwear")],
        )
        results = evaluate_eligibility(order)
        assert results[0].returnable is True
        assert results[0].matched_rule == "footwear_within_window"

    def test_unconfigured_category_falls_back_to_order_window(self) -> None:
        """A category with no specific rule uses policy.return_window_days."""
        order = _make_order(
            delivery_date=datetime.now() - timedelta(days=20),
            articles=[_make_article(category="accessories")],
            return_window_days=30,
        )
        results = evaluate_eligibility(order)
        assert results[0].returnable is True
        assert results[0].matched_rule == "within_return_window"

    def test_unconfigured_category_respects_order_window_expiry(self) -> None:
        order = _make_order(
            delivery_date=datetime.now() - timedelta(days=35),
            articles=[_make_article(category="accessories")],
            return_window_days=30,
        )
        results = evaluate_eligibility(order)
        assert results[0].returnable is False
        assert results[0].matched_rule == "return_window_expired"

    def test_electronics_ignores_order_level_window(self) -> None:
        """Even if the order has a 30-day window, electronics cap at 14."""
        order = _make_order(
            delivery_date=datetime.now() - timedelta(days=20),
            articles=[_make_article(category="electronics")],
            return_window_days=30,
        )
        results = evaluate_eligibility(order)
        assert results[0].returnable is False
        assert results[0].matched_rule == "electronics_window_expired"


class TestMultipleArticles:
    def test_each_article_evaluated_independently(self) -> None:
        order = _make_order(
            delivery_date=datetime.now() - timedelta(days=5),
            articles=[
                _make_article(sku="A", is_digital=False),
                _make_article(sku="B", is_digital=True),
                _make_article(sku="C", is_final_sale=True),
            ],
        )
        results = evaluate_eligibility(order)
        assert len(results) == 3
        assert results[0].returnable is True
        assert results[1].returnable is False
        assert results[2].returnable is False

    def test_results_preserve_article_order(self) -> None:
        order = _make_order(
            delivery_date=datetime.now() - timedelta(days=5),
            articles=[
                _make_article(sku="FIRST"),
                _make_article(sku="SECOND"),
            ],
        )
        results = evaluate_eligibility(order)
        assert results[0].article.sku == "FIRST"
        assert results[1].article.sku == "SECOND"
