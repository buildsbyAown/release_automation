BASE_FEE = 5.00
PER_KG_FEE = 1.50


def shipping_fee(weight_kg):
    """Return the shipping fee for a parcel of the given weight."""
    if weight_kg < 0:
        raise ValueError("Weight cannot be negative.")
    return round(BASE_FEE + weight_kg * PER_KG_FEE, 2)
