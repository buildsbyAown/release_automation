from discounts import apply_coupon


def calculate_total(price, coupon="WELCOME10"):
    discounted_price = apply_coupon(price, coupon)
    # Apply tax after discount.
    return round(discounted_price * 1.10, 2)
