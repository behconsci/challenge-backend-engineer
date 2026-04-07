"""Tests for the Django views."""

from unittest.mock import patch

import pytest
from django.test import Client

pytestmark = pytest.mark.django_db


@pytest.fixture()
def client() -> Client:
    return Client()


_TOKENS = {
    "RMA-1001": "mnJqysTweQXf4mbutgnyfSy4sq4pR-JIHAHSvgSZLF8",
    "RMA-1002": "mEw1P3KSGS9IM_uyLAR-GRE5ZUe768KZEXsvsCMJNXY",
}


def _lookup(client: Client, order_number: str = "RMA-1001", identifier: str = "alex@example.com") -> None:
    """Helper: authenticate via the lookup form including the return token."""
    client.post("/returns/", {
        "order_number": order_number,
        "identifier": identifier,
        "token": _TOKENS.get(order_number, ""),
    })


class TestLookupView:
    def test_get_returns_200(self, client: Client) -> None:
        response = client.get("/returns/")
        assert response.status_code == 200

    def test_get_contains_form(self, client: Client) -> None:
        response = client.get("/returns/")
        assert b"order_number" in response.content

    def test_valid_email_redirects(self, client: Client) -> None:
        response = client.post(
            "/returns/",
            {
                "order_number": "RMA-1001",
                "identifier": "alex@example.com",
                "token": _TOKENS["RMA-1001"],
            },
        )
        assert response.status_code == 302
        assert "/articles/" in response.headers["Location"]

    def test_valid_zip_redirects(self, client: Client) -> None:
        response = client.post(
            "/returns/",
            {
                "order_number": "RMA-1001",
                "identifier": "10115",
                "token": _TOKENS["RMA-1001"],
            },
        )
        assert response.status_code == 302

    def test_valid_token_redirects(self, client: Client) -> None:
        response = client.post("/returns/", {
            "order_number": "RMA-1001",
            "identifier": "alex@example.com",
            "token": _TOKENS["RMA-1001"],
        })
        assert response.status_code == 302

    def test_missing_token_rejected(self, client: Client) -> None:
        response = client.post("/returns/", {
            "order_number": "RMA-1001",
            "identifier": "alex@example.com",
            "token": "",
        })
        assert response.status_code == 200
        assert b"not found" in response.content.lower()

    def test_wrong_token_rejected(self, client: Client) -> None:
        response = client.post("/returns/", {
            "order_number": "RMA-1001",
            "identifier": "alex@example.com",
            "token": "wrong-token",
        })
        assert response.status_code == 200
        assert b"not found" in response.content.lower()

    def test_invalid_credentials_shows_error(self, client: Client) -> None:
        response = client.post(
            "/returns/",
            {
                "order_number": "RMA-1001",
                "identifier": "wrong@example.com",
            },
        )
        assert response.status_code == 200
        assert b"not found" in response.content.lower()

    def test_empty_fields_returns_form(self, client: Client) -> None:
        response = client.post(
            "/returns/",
            {
                "order_number": "",
                "identifier": "",
            },
        )
        assert response.status_code == 200


class TestArticlesView:
    def test_unauthenticated_redirects(self, client: Client) -> None:
        response = client.get("/returns/RMA-1001/articles/")
        assert response.status_code == 302

    def test_wrong_order_number_redirects(self, client: Client) -> None:
        _lookup(client)
        response = client.get("/returns/RMA-9999/articles/")
        assert response.status_code == 302

    def test_authenticated_shows_articles(self, client: Client) -> None:
        _lookup(client)
        response = client.get("/returns/RMA-1001/articles/")
        assert response.status_code == 200
        assert b"TSHIRT-BLK-M" in response.content

    def test_ineligible_article_is_not_selectable(self, client: Client) -> None:
        _lookup(client)
        response = client.get("/returns/RMA-1001/articles/")
        assert response.status_code == 200
        # The digital ebook should appear disabled
        assert b"EBOOK-RETURNS" in response.content
        assert b'disabled' in response.content


class TestArticlesViewPost:
    def test_post_without_selection_redirects_back(self, client: Client) -> None:
        _lookup(client)
        response = client.post("/returns/RMA-1001/articles/", {})
        assert response.status_code == 302
        assert "/articles/" in response.headers["Location"]

    def test_post_with_selection_redirects_to_confirm(self, client: Client) -> None:
        _lookup(client)
        response = client.post(
            "/returns/RMA-1001/articles/",
            {"selected_skus": "TSHIRT-BLK-M", "qty_TSHIRT-BLK-M": "1"},
        )
        assert response.status_code == 302
        assert "/confirm/" in response.headers["Location"]

    def test_post_stores_selection_in_session(self, client: Client) -> None:
        _lookup(client)
        client.post(
            "/returns/RMA-1001/articles/",
            {"selected_skus": "TSHIRT-BLK-M", "qty_TSHIRT-BLK-M": "1"},
        )
        assert client.session["return_selections"] == {"TSHIRT-BLK-M": 1}

    def test_post_accumulates_selections_across_submissions(self, client: Client) -> None:
        _lookup(client)
        client.post(
            "/returns/RMA-1001/articles/",
            {"selected_skus": "TSHIRT-BLK-M", "qty_TSHIRT-BLK-M": "1"},
        )
        client.post(
            "/returns/RMA-1001/articles/",
            {"selected_skus": "TSHIRT-BLK-M", "qty_TSHIRT-BLK-M": "1"},
        )
        assert client.session["return_selections"]["TSHIRT-BLK-M"] == 2

    def test_returned_article_shown_as_pending(self, client: Client) -> None:
        _lookup(client)
        client.post(
            "/returns/RMA-1001/articles/",
            {"selected_skus": "TSHIRT-BLK-M", "qty_TSHIRT-BLK-M": "1"},
        )
        response = client.get("/returns/RMA-1001/articles/")
        assert b"Return processing" in response.content

    def test_unauthenticated_post_redirects(self, client: Client) -> None:
        response = client.post(
            "/returns/RMA-1001/articles/",
            {"selected_skus": "TSHIRT-BLK-M", "qty_TSHIRT-BLK-M": "1"},
        )
        assert response.status_code == 302
        assert "/articles/" not in response.headers["Location"]


class TestConfirmView:
    def _submit(self, client: Client) -> None:
        _lookup(client)
        client.post(
            "/returns/RMA-1001/articles/",
            {"selected_skus": "TSHIRT-BLK-M", "qty_TSHIRT-BLK-M": "1"},
        )

    def test_without_session_redirects_to_articles(self, client: Client) -> None:
        _lookup(client)
        response = client.get("/returns/RMA-1001/confirm/")
        assert response.status_code == 302
        assert "/articles/" in response.headers["Location"]

    def test_unauthenticated_redirects_to_lookup(self, client: Client) -> None:
        response = client.get("/returns/RMA-1001/confirm/")
        assert response.status_code == 302
        assert response.headers["Location"].endswith("/returns/")

    def test_shows_processing_banner(self, client: Client) -> None:
        self._submit(client)
        response = client.get("/returns/RMA-1001/confirm/")
        assert response.status_code == 200
        assert b"being processed" in response.content

    def test_shows_selected_article(self, client: Client) -> None:
        self._submit(client)
        response = client.get("/returns/RMA-1001/confirm/")
        assert b"TSHIRT-BLK-M" in response.content

    def test_shows_promotions(self, client: Client) -> None:
        self._submit(client)
        response = client.get("/returns/RMA-1001/confirm/")
        assert b"While you wait" in response.content

    def test_shows_at_most_three_promotions(self, client: Client) -> None:
        self._submit(client)
        response = client.get("/returns/RMA-1001/confirm/")
        # Each promo renders its badge text; count occurrences of the shared label sentinel
        # The promotions.json badges are: "20% off", "New arrival", "Bestseller", "Bundle deal"
        # With [:3] slice only the first three should appear.
        badge_hits = sum(
            response.content.count(label)
            for label in (b"20% off", b"New arrival", b"Bestseller", b"Bundle deal")
        )
        assert badge_hits == 3

    def test_stamps_confirmed_at_on_first_visit(self, client: Client) -> None:
        self._submit(client)
        assert "return_confirmed_at" not in client.session
        client.get("/returns/RMA-1001/confirm/")
        assert "return_confirmed_at" in client.session

    def test_does_not_reset_timestamp_on_revisit(self, client: Client) -> None:
        self._submit(client)
        client.get("/returns/RMA-1001/confirm/")
        first_ts = client.session["return_confirmed_at"]
        client.get("/returns/RMA-1001/confirm/")
        assert client.session["return_confirmed_at"] == first_ts

    def test_after_30s_renders_success_page(self, client: Client) -> None:
        self._submit(client)
        client.get("/returns/RMA-1001/confirm/")  # stamp the time
        with patch("portal.views.time.time", return_value=client.session["return_confirmed_at"] + 31):
            response = client.get("/returns/RMA-1001/confirm/")
        assert response.status_code == 200
        assert b"on its way back to you" in response.content

    def test_success_clears_session(self, client: Client) -> None:
        self._submit(client)
        client.get("/returns/RMA-1001/confirm/")
        with patch("portal.views.time.time", return_value=client.session["return_confirmed_at"] + 31):
            client.get("/returns/RMA-1001/confirm/")
        assert "return_selections" not in client.session
        assert "return_confirmed_at" not in client.session


class TestEndToEndReturnFlow:
    """Full happy-path walk-through: lookup → articles → confirm → success."""

    def test_full_flow(self, client: Client) -> None:
        # 1. Lookup
        response = client.post(
            "/returns/",
            {"order_number": "RMA-1001", "identifier": "alex@example.com", "token": _TOKENS["RMA-1001"]},
        )
        assert response.status_code == 302

        # 2. Articles page loads
        response = client.get("/returns/RMA-1001/articles/")
        assert response.status_code == 200

        # 3. Submit selection
        response = client.post(
            "/returns/RMA-1001/articles/",
            {"selected_skus": "TSHIRT-BLK-M", "qty_TSHIRT-BLK-M": "1"},
        )
        assert response.status_code == 302

        # 4. Confirm page shows processing state
        response = client.get("/returns/RMA-1001/confirm/")
        assert response.status_code == 200
        assert b"being processed" in response.content
        assert b"TSHIRT-BLK-M" in response.content

        # 5. After 30s → success
        confirmed_at = client.session["return_confirmed_at"]
        with patch("portal.views.time.time", return_value=confirmed_at + 31):
            response = client.get("/returns/RMA-1001/confirm/")
        assert b"on its way back to you" in response.content

        # 6. Session is clean after success
        assert "return_selections" not in client.session
        assert "return_confirmed_at" not in client.session
