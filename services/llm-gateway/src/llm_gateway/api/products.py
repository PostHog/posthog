from fastapi import HTTPException

ALLOWED_PRODUCTS = frozenset({"llm_gateway", "wizard", "array"})


def validate_product(product: str) -> str:
    if product not in ALLOWED_PRODUCTS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid product '{product}'. Allowed products: {', '.join(sorted(ALLOWED_PRODUCTS))}",
        )
    return product
