import json
import time
from pathlib import Path

from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.views import View

from portal.forms import LookupForm
from portal.services.eligibility import evaluate_eligibility
from portal.services.order_store import find_order, get_order

_PROMOTIONS_PATH = Path(__file__).resolve().parent / "data" / "promotions.json"


def _load_promotions() -> list[dict]:
    with _PROMOTIONS_PATH.open() as f:
        return json.load(f)["promotions"]


def _verify_session(request: HttpRequest, order_number: str) -> bool:
    """Return True only if the session was established for this exact order,
    the stored identifier matches, and the return token is valid."""
    if request.session.get("order_number") != order_number:
        return False
    identifier = request.session.get("identifier", "")
    if not identifier:
        return False
    token = request.session.get("return_token", "")
    return find_order(order_number, identifier, token) is not None


class LookupView(View):
    """Order lookup page – validates order number + email / zip."""

    def get(self, request: HttpRequest) -> HttpResponse:
        token = request.GET.get("token", "")
        form = LookupForm(initial={"token": token})
        return render(request, "returns/lookup.html", {"form": form, "token_from_url": token})

    def post(self, request: HttpRequest) -> HttpResponse:
        form = LookupForm(request.POST)
        if form.is_valid():
            order = find_order(
                form.cleaned_data["order_number"],
                form.cleaned_data["identifier"],
                form.cleaned_data.get("token", ""),
            )
            if order is None:
                form.add_error(None, "Order not found or credentials do not match.")
            else:
                request.session["order_number"] = order.order_number
                request.session["identifier"] = form.cleaned_data["identifier"]
                request.session["return_token"] = form.cleaned_data.get("token", "")
                return redirect("articles", order_number=order.order_number)

        token = request.POST.get("token", "")
        return render(request, "returns/lookup.html", {"form": form, "token_from_url": token})


class ArticlesView(View):
    """Articles page – shows items in the order with eligibility info."""

    def get(self, request: HttpRequest, order_number: str) -> HttpResponse:
        if not _verify_session(request, order_number):
            return redirect("lookup")

        order = get_order(order_number)
        if order is None:
            return redirect("lookup")

        results = evaluate_eligibility(order)
        pending_returns = request.session.get("return_selections", {})
        article_rows = []
        for result in results:
            pending_qty = pending_returns.get(result.article.sku, 0)
            remaining_qty = max(
                result.article.quantity - result.article.quantity_returned - pending_qty,
                0,
            )
            article_rows.append(
                {
                    "result": result,
                    "remaining_qty": remaining_qty,
                    "quantity_options": list(range(1, remaining_qty + 1)),
                    "selectable": result.returnable and remaining_qty > 0,
                    "pending_qty": pending_qty,
                }
            )

        return render(
            request,
            "returns/articles.html",
            {
                "order": order,
                "results": results,
                "article_rows": article_rows,
            },
        )

    def post(self, request: HttpRequest, order_number: str) -> HttpResponse:
        if not _verify_session(request, order_number):
            return redirect("lookup")

        selected_skus = request.POST.getlist("selected_skus")
        if not selected_skus:
            return redirect("articles", order_number=order_number)

        existing = dict(request.session.get("return_selections", {}))
        for sku in selected_skus:
            qty_key = f"qty_{sku}"
            try:
                qty = int(request.POST.get(qty_key, 1))
            except ValueError:
                qty = 1
            existing[sku] = existing.get(sku, 0) + qty

        request.session["return_selections"] = existing
        return redirect("confirm", order_number=order_number)


_PROCESSING_SECONDS = 30


class ConfirmView(View):
    """Confirmation page – summarises what the user is returning.

    On first visit the return is stamped with a timestamp.  After
    ``_PROCESSING_SECONDS`` seconds the page transitions to success.
    """

    def get(self, request: HttpRequest, order_number: str) -> HttpResponse:
        if not _verify_session(request, order_number):
            return redirect("lookup")

        selections = request.session.get("return_selections")
        if not selections:
            return redirect("articles", order_number=order_number)

        order = get_order(order_number)
        if order is None:
            return redirect("lookup")

        # Stamp the submission time on first visit.
        if "return_confirmed_at" not in request.session:
            request.session["return_confirmed_at"] = time.time()

        elapsed = time.time() - request.session["return_confirmed_at"]

        if elapsed >= _PROCESSING_SECONDS:
            # Clear session state so the flow can start fresh.
            request.session.pop("return_selections", None)
            request.session.pop("return_confirmed_at", None)
            return render(request, "returns/success.html", {"order": order})

        confirm_rows = []
        for article in order.articles:
            qty = selections.get(article.sku)
            if qty:
                confirm_rows.append({"article": article, "qty": qty, "subtotal": article.price * qty})

        remaining_ms = int((_PROCESSING_SECONDS - elapsed) * 1000)
        return render(
            request,
            "returns/confirm.html",
            {
                "order": order,
                "confirm_rows": confirm_rows,
                "remaining_ms": remaining_ms,
                "promotions": _load_promotions()[:3],
            },
        )
