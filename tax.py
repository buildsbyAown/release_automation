TAX_RATES = {
    "default": 0.10,
    "CA": 0.0725,
    "NY": 0.08875,
    "TX": 0.0625,
}


def apply_tax(amount, region="default"):
    """Return the amount with the region's sales tax added."""
    rate = TAX_RATES.get(region, TAX_RATES["default"])
    return round(amount * (1 + rate), 2)
