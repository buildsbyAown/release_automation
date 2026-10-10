DEFAULT_DISCOUNT_RATE = 0.10

COUPONS = {
    "WELCOME10": 0.10,
    "SPRING20": 0.20,
    "VIP30": 0.30,
}


def apply_discount(price, rate=DEFAULT_DISCOUNT_RATE):
    """Return the price after applying a percentage discount."""
    if not 0 <= rate < 1:
        raise ValueError("Discount rate must be between 0 and 1.")
    return round(price * (1 - rate), 2)


def apply_coupon(price, code):
    """Apply a coupon code; unknown codes fall back to the default discount."""
    rate = COUPONS.get(code.strip().upper(), DEFAULT_DISCOUNT_RATE)
    return apply_discount(price, rate)
