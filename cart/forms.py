from django import forms

MAX_QTY_PER_ITEM = 99


class CartQuantityForm(forms.Form):
    quantity = forms.IntegerField(
        label="Количество", min_value=1, max_value=MAX_QTY_PER_ITEM, initial=1,
        error_messages={
            "min_value": "Количество должно быть не меньше 1.",
            "max_value": f"Не больше {MAX_QTY_PER_ITEM} шт. одного товара.",
            "invalid": "Введите целое число.",
            "required": "Укажите количество.",
        },
    )


class CartUpdateForm(forms.Form):
    """Как CartQuantityForm, но 0 означает «удалить»."""

    quantity = forms.IntegerField(
        min_value=0, max_value=MAX_QTY_PER_ITEM,
        error_messages={
            "min_value": "Количество не может быть отрицательным.",
            "max_value": f"Не больше {MAX_QTY_PER_ITEM} шт. одного товара.",
            "invalid": "Введите целое число.",
            "required": "Укажите количество.",
        },
    )
