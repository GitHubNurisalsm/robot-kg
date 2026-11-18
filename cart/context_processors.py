from .cart import Cart


def cart(request):
    # Только чтение сессии — без запросов к БД на каждой странице.
    return {"cart_count": len(Cart(request))}
