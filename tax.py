TAX_RATES = {
    "default": 0.10,
    "CA": 0.0725,
    "NY": 0.08875,
    "TX": 0.0625,
}

TAX_EXEMPT_CATEGORIES = {"groceries", "medicine"}


def apply_tax(amount, region="default", category=None):
    """Return the amount with the region's sales tax added; exempt categories are not taxed."""
    if category in TAX_EXEMPT_CATEGORIES:
        return round(amount, 2)
    rate = TAX_RATES.get(region, TAX_RATES["default"])
    return round(amount * (1 + rate), 2)
