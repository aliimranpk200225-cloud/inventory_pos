from decimal import Decimal, InvalidOperation

from django import template

from inventory.stock import format_quantity

register = template.Library()


@register.filter
def qty(value):
    return format_quantity(value)


@register.filter
def rs(value):
    try:
        amount = Decimal(str(value or 0))
    except (InvalidOperation, TypeError, ValueError):
        return value
    formatted = f'{amount:,.2f}'
    if amount < 0:
        return f'-{formatted[1:]}' if formatted.startswith('-') else formatted
    return formatted
