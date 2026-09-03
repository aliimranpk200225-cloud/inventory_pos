from django import forms

from .models import PurchaseItem


class PurchaseItemForm(forms.ModelForm):
    class Meta:
        model = PurchaseItem
        fields = '__all__'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['unit_price'].required = False
        self.fields['unit_price'].help_text = (
            'Defaults to the product unit purchase price when you pick a product.'
        )

    def clean(self):
        cleaned = super().clean()
        product_unit = cleaned.get('product_unit')
        unit_price = cleaned.get('unit_price')
        if product_unit is not None and unit_price is None:
            cleaned['unit_price'] = product_unit.purchase_price
        return cleaned
