DEFAULT_DISCOUNT_RATE = 0.10


def apply_discount(price, rate=DEFAULT_DISCOUNT_RATE):
    """Return the price after applying a percentage discount."""
    if not 0 <= rate < 1:
        raise ValueError("Discount rate must be between 0 and 1.")
    return round(price * (1 - rate), 2)
