TAX_RATE = 0.10


def apply_tax(amount):
    """Return the amount with sales tax added."""
    return round(amount * (1 + TAX_RATE), 2)
