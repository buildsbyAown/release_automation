def calculate_total(price):
    discounted_price = price * 0.90
    # Apply tax after discount.
    return round(discounted_price * 1.10, 2)