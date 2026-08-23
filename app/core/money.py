from decimal import Decimal, ROUND_HALF_UP

_MONEY = Decimal("0.01")
_ZERO = Decimal("0.00")


def as_money(value: Decimal | None) -> Decimal:
    amount = Decimal(str(value)) if value is not None else _ZERO
    return amount.quantize(_MONEY, rounding=ROUND_HALF_UP)
