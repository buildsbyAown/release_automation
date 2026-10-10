from discounts import apply_coupon


def build_summary(items, coupon="WELCOME10"):
    """Summarise a list of (name, price, quantity) items with the coupon applied."""
    lines = [
        {"name": name, "quantity": qty, "line_total": round(price * qty, 2)}
        for name, price, qty in items
    ]
    subtotal = round(sum(line["line_total"] for line in lines), 2)
    discounted = apply_coupon(subtotal, coupon)
    return {
        "lines": lines,
        "subtotal": subtotal,
        "discount": round(subtotal - discounted, 2),
        "total": discounted,
    }


def format_summary(summary):
    """Render a summary as plain text."""
    rows = [f"{line['quantity']} x {line['name']}: {line['line_total']:.2f}" for line in summary["lines"]]
    rows.append(f"Subtotal: {summary['subtotal']:.2f}")
    rows.append(f"Discount: -{summary['discount']:.2f}")
    rows.append(f"Total: {summary['total']:.2f}")
    return "\n".join(rows)
