"""Open Food Facts adapter parses product responses (no network; mock transport)."""

import httpx

from lars.adapters.nutrition import OpenFoodFactsClient

PRODUCT = {
    "status": 1,
    "product": {
        "product_name": "Chobani Vanilla",
        "serving_size": "150g",
        "nutriments": {
            "energy-kcal_serving": 140,
            "proteins_serving": 12,
            "carbohydrates_serving": 20,
            "fat_serving": 2.5,
        },
    },
}


async def test_by_barcode_parses_serving_values() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=PRODUCT)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        facts = await OpenFoodFactsClient(client).by_barcode("3017620422003")

    assert facts is not None
    assert facts.name == "Chobani Vanilla"
    assert facts.calories == 140
    assert facts.protein_g == 12
    assert facts.serving == "150g"


async def test_by_barcode_falls_back_to_100g() -> None:
    payload = {
        "status": 1,
        "product": {"product_name": "Generic", "nutriments": {"energy-kcal_100g": 250}},
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        facts = await OpenFoodFactsClient(client).by_barcode("123")

    assert facts is not None
    assert facts.calories == 250
    assert facts.protein_g is None


async def test_by_barcode_not_found_returns_none() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": 0})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        assert await OpenFoodFactsClient(client).by_barcode("000") is None
