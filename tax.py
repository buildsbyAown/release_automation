TAX_RATES = {
    "default": 0.10,
    "CA": 0.0725,
    "NY": 0.08875,
    "TX": 0.0625,
}

TAX_EXEMPT_CATEGORIES = {"groceries", "medicine"}


def tax_amount(amount, region="default", category=None):
    """Return only the tax owed on the amount."""
    if category in TAX_EXEMPT_CATEGORIES:
        return 0.0
    rate = TAX_RATES.get(region, TAX_RATES["default"])
    return round(amount * rate, 2)


def apply_tax(amount, region="default", category=None):
    """Return the amount with the region's sales tax added; exempt categories are not taxed."""
    return round(amount + tax_amount(amount, region, category), 2)
