"""Open Food Facts adapter: resolve a barcode to nutrition facts."""

import asyncio
from typing import Any, Protocol

import httpx

from lars.domain.models import NutritionFacts
from lars.retry import Sleep, retry_async

_BASE_URL = "https://world.openfoodfacts.org"
_FIELDS = "product_name,nutriments,serving_size"


class NutritionLookup(Protocol):
    async def by_barcode(self, barcode: str) -> NutritionFacts | None: ...


class OpenFoodFactsClient:
    """Thin client over the Open Food Facts product API."""

    def __init__(
        self,
        client: httpx.AsyncClient,
        base_url: str = _BASE_URL,
        *,
        attempts: int = 3,
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        self._client = client
        self._base_url = base_url
        self._attempts = attempts
        self._sleep = sleep

    async def by_barcode(self, barcode: str) -> NutritionFacts | None:
        url = f"{self._base_url}/api/v2/product/{barcode}.json"
        try:
            response = await retry_async(
                lambda: self._client.get(url, params={"fields": _FIELDS}),
                attempts=self._attempts,
                exceptions=(httpx.HTTPError,),
                sleep=self._sleep,
            )
        except httpx.HTTPError:
            return None
        if response.status_code != 200:
            return None

        data = response.json()
        if data.get("status") != 1:
            return None
        product = data.get("product", {})
        nutriments: dict[str, Any] = product.get("nutriments", {})

        def pick(key: str) -> float | None:
            value = nutriments.get(f"{key}_serving")
            if value is None:
                value = nutriments.get(f"{key}_100g")
            return float(value) if isinstance(value, (int, float)) else None

        return NutritionFacts(
            name=product.get("product_name") or barcode,
            serving=product.get("serving_size"),
            calories=pick("energy-kcal"),
            protein_g=pick("proteins"),
            carbs_g=pick("carbohydrates"),
            fat_g=pick("fat"),
        )
