BASE_FEE = 5.00
PER_KG_FEE = 1.50
FREE_SHIPPING_THRESHOLD = 100.00


def shipping_fee(weight_kg, order_total=0.0):
    """Return the shipping fee; orders at or above the threshold ship free."""
    if weight_kg < 0:
        raise ValueError("Weight cannot be negative.")
    if order_total >= FREE_SHIPPING_THRESHOLD:
        return 0.0
    return round(BASE_FEE + weight_kg * PER_KG_FEE, 2)
