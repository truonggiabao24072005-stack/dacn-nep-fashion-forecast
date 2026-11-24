from store.models import Role, SystemGuard


def navigation(request):
    u = request.user
    if not u.is_authenticated:
        return {}
    mode = SystemGuard.objects.filter(pk=1).values_list("data_mode", flat=True).first()
    return {
        "is_admin": u.role == Role.ADMIN,
        "can_sell": u.role in [Role.ADMIN, Role.SALES],
        "can_receive": u.role in [Role.ADMIN, Role.WAREHOUSE],
        "data_mode": mode or "OPERATIONAL",
    }
