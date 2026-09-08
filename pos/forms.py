from decimal import Decimal

from django import forms

from .models import CashMovement, Sale


class MoneyForm(forms.Form):
    amount = forms.DecimalField(
        min_value=Decimal('0.00'),
        max_digits=12,
        decimal_places=2,
        label='Amount (Rs.)',
    )


class OpeningCashForm(MoneyForm):
    amount = forms.DecimalField(
        min_value=Decimal('0.00'),
        max_digits=12,
        decimal_places=2,
        label='Opening cash (Rs.)',
        help_text='Physical cash currently in the counter. This is not a sale.',
    )


class ClosingCashForm(MoneyForm):
    amount = forms.DecimalField(
        min_value=Decimal('0.00'),
        max_digits=12,
        decimal_places=2,
        label='Actual cash in counter (Rs.)',
    )


class CashMovementForm(forms.Form):
    amount = forms.DecimalField(
        min_value=Decimal('0.01'),
        max_digits=12,
        decimal_places=2,
        label='Amount (Rs.)',
    )
    reason = forms.CharField(max_length=200, required=False, label='Reason')
    movement_type = forms.ChoiceField(
        choices=(
            (CashMovement.MovementType.CASH_OUT, 'Cash out'),
            (CashMovement.MovementType.EXPENSE, 'Expense'),
        ),
        required=False,
    )
    payment_method = forms.ChoiceField(
        choices=Sale.PaymentMethod.choices,
        initial=Sale.PaymentMethod.CASH,
        required=False,
        label='Refund method',
    )
