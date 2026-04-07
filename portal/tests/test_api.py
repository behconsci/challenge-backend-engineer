from __future__ import annotations

import pytest
from rest_framework.test import APIClient

pytestmark = pytest.mark.django_db


_TOKENS = {
    "RMA-1001": "mnJqysTweQXf4mbutgnyfSy4sq4pR-JIHAHSvgSZLF8",
    "RMA-1002": "mEw1P3KSGS9IM_uyLAR-GRE5ZUe768KZEXsvsCMJNXY",
}


def _lookup(client: APIClient, order_number: str, identifier: str) -> None:
    client.post("/api/returns/lookup/", {
        "order_number": order_number,
        "identifier": identifier,
        "token": _TOKENS.get(order_number, ""),
    }, format="json")


class TestReturnsApiViewSet:
    def test_lookup_with_valid_credentials_returns_articles_url(self) -> None:
        client = APIClient()

        response = client.post(
            "/api/returns/lookup/",
            {
                "order_number": "RMA-1001",
                "identifier": "alex@example.com",
                "token": _TOKENS["RMA-1001"],
            },
            format="json",
        )

        assert response.status_code == 200
        assert response.data["order_number"] == "RMA-1001"
        assert response.data["articles_url"].endswith("/api/returns/RMA-1001/articles/")

    def test_lookup_with_invalid_credentials_returns_400(self) -> None:
        client = APIClient()

        response = client.post(
            "/api/returns/lookup/",
            {
                "order_number": "RMA-1001",
                "identifier": "wrong@example.com",
            },
            format="json",
        )

        assert response.status_code == 400
        assert "not found" in response.data["detail"].lower()

    def test_articles_requires_prior_lookup(self) -> None:
        client = APIClient()

        response = client.get("/api/returns/RMA-1001/articles/")

        assert response.status_code == 403

    def test_lookup_without_token_is_rejected(self) -> None:
        client = APIClient()
        response = client.post("/api/returns/lookup/", {
            "order_number": "RMA-1001",
            "identifier": "alex@example.com",
            "token": "",
        }, format="json")
        assert response.status_code == 400

    def test_lookup_with_wrong_token_is_rejected(self) -> None:
        client = APIClient()
        response = client.post("/api/returns/lookup/", {
            "order_number": "RMA-1001",
            "identifier": "alex@example.com",
            "token": "wrong-token",
        }, format="json")
        assert response.status_code == 400

    def test_articles_for_different_order_is_forbidden(self) -> None:
        """Exploit: authenticate as RMA-1001, then request RMA-1002's articles.

        The API must reject this — session order_number must match the URL.
        Before the fix, this returned HTTP 200 with RMA-1002's full order data
        (email, address, articles) to an unauthenticated-for-that-order caller.
        """
        client = APIClient()
        _lookup(client, "RMA-1001", "alex@example.com")

        response = client.get("/api/returns/RMA-1002/articles/")

        assert response.status_code == 403

    def test_articles_after_lookup_returns_order_and_eligibility(self) -> None:
        client = APIClient()
        lookup_response = client.post(
            "/api/returns/lookup/",
            {
                "order_number": "RMA-1001",
                "identifier": "alex@example.com",
                "token": _TOKENS["RMA-1001"],
            },
            format="json",
        )
        assert lookup_response.status_code == 200

        response = client.get("/api/returns/RMA-1001/articles/")

        assert response.status_code == 200
        assert response.data["order"]["order_number"] == "RMA-1001"
        assert len(response.data["results"]) == 2

        first = response.data["results"][0]
        second = response.data["results"][1]
        assert first["article"]["sku"] == "TSHIRT-BLK-M"
        assert first["selectable"] is True
        assert first["quantity_options"] == [1]

        assert second["article"]["sku"] == "EBOOK-RETURNS"
        assert second["returnable"] is False
        assert second["selectable"] is False
