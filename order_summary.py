from discounts import apply_coupon


def build_summary(items, coupon="WELCOME10"):
    """Summarise a list of (name, price, quantity) items with the coupon applied."""
    subtotal = round(sum(price * qty for _, price, qty in items), 2)
    discounted = apply_coupon(subtotal, coupon)
    return {
        "subtotal": subtotal,
        "discount": round(subtotal - discounted, 2),
        "total": discounted,
    }
