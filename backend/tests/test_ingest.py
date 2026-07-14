import json

import pytest

from app.services import ingest


def test_normalize_store_url():
    assert ingest.normalize_store_url("ndevu.com") == "https://ndevu.com"
    assert ingest.normalize_store_url("https://shop.example.com/collections/all") == "https://shop.example.com"
    assert ingest.normalize_store_url("  http://x.io ") == "https://x.io"


def test_strip_html():
    assert ingest._strip_html("<p>Hello <b>world</b></p>\n\n more") == "Hello world more"
    assert ingest._strip_html(None) == ""


def test_chunk_splits_and_preserves_words():
    text = "word " * 500
    chunks = ingest._chunk(text.strip(), size=700)
    assert len(chunks) > 1
    assert " ".join(chunks).split() == text.split()


class FakeResponse:
    def __init__(self, status_code=200, payload=None, content_type="application/json"):
        self.status_code = status_code
        self._payload = payload or {}
        self.headers = {"content-type": content_type}

    def json(self):
        return self._payload


class FakeClient:
    """Simulates a Shopify /products.json with two pages of 250 + 3 products."""

    def __init__(self, *args, **kwargs):
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url, params=None):
        self.calls.append((url, params))
        page = params["page"]
        if page == 1:
            products = [{"id": i, "title": f"P{i}"} for i in range(250)]
        elif page == 2:
            products = [{"id": 250 + i, "title": f"P{250 + i}"} for i in range(3)]
        else:
            products = []
        return FakeResponse(payload={"products": products})


class NotShopifyClient(FakeClient):
    async def get(self, url, params=None):
        return FakeResponse(status_code=200, payload={}, content_type="text/html")


async def test_shopify_pagination(monkeypatch):
    monkeypatch.setattr(ingest.httpx, "AsyncClient", FakeClient)
    monkeypatch.setattr(ingest.settings, "max_products_ingest", 500)
    products = await ingest.fetch_shopify_products("https://x.com")
    assert len(products) == 253
    assert products[0]["title"] == "P0"
    assert products[-1]["title"] == "P252"


async def test_shopify_ingest_cap(monkeypatch):
    monkeypatch.setattr(ingest.httpx, "AsyncClient", FakeClient)
    monkeypatch.setattr(ingest.settings, "max_products_ingest", 250)
    products = await ingest.fetch_shopify_products("https://x.com")
    assert len(products) == 250  # cap stops the pager after page 1


async def test_non_shopify_returns_none(monkeypatch):
    monkeypatch.setattr(ingest.httpx, "AsyncClient", NotShopifyClient)
    assert await ingest.fetch_shopify_products("https://x.com") is None


def test_design_heuristic():
    assert ingest._looks_like_design({"title": "Faith Graphic Print Tee"})
    assert not ingest._looks_like_design({"title": "Plain Hoodie"})
