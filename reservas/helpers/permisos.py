from django.http import Http404
from django.shortcuts import get_object_or_404

from ..models import Sucursal
from .. import tenancy


def user_can_manage_sucursal(user, sucursal: Sucursal) -> bool:
    return tenancy.user_can_manage_sucursal(user, sucursal)


def assert_can_manage(request, sucursal_id: int) -> Sucursal:
    s = get_object_or_404(Sucursal, pk=sucursal_id)
    if not user_can_manage_sucursal(request.user, s):
        raise Http404()  # así nadie sabrá si existe o no
    return s
