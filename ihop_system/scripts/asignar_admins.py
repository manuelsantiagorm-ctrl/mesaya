from django.contrib.auth import get_user_model
from django.db import transaction
from django.core.exceptions import ObjectDoesNotExist

U = get_user_model()

# Admins: (email, nombre_del_país, contraseña)
ADMINS = [
    ("admin.sa@ihop.com", "Arabia Saudita", "i2rBWWD5d6eLpg"),
    ("admin.ar@ihop.com", "Argentina", "XgcoUwMCam7_bA"),
    ("admin.bh@ihop.com", "Baréin", "E-DiMFzNVZ-1EA"),
    ("admin.ca@ihop.com", "Canadá", "4wpFlB5_m_Z6DQ"),
    ("admin.qa@ihop.com", "Catar", "nkAPfgqRgsywlw"),
    ("admin.cl@ihop.com", "Chile", "q5WWalhhcyvmxg"),
    ("admin.co@ihop.com", "Colombia", "9vT0T9sVtzfdng"),
    ("admin.ec@ihop.com", "Ecuador", "rDPOcOnNC9Kgsg"),
    ("admin.ae@ihop.com", "Emiratos Árabes Unidos", "6klo6Vcx6bHZww"),
    ("admin.es@ihop.com", "España", "tTcgOYImJbcTWw"),
    ("admin.us@ihop.com", "Estados Unidos", "BUyBtQY6eqZ5cQ"),
    ("admin.ph@ihop.com", "Filipinas", "fnF9Pta8zFyBJQ"),
    ("admin.gt@ihop.com", "Guatemala", "CORJRU_XM4nbqw"),
    ("admin.kw@ihop.com", "Kuwait", "sdfBt7RVkCNHpw"),
    ("admin.mx@ihop.com", "México", "VGiappv6jzGxWg"),
    ("admin.pe@ihop.com", "Perú", "oUHH9bm-VHSUvg"),
]

# Importa modelos necesarios sin romper si cambió la estructura
try:
    from reservas.models import Pais
except Exception as e:
    raise RuntimeError(f"No pude importar Pais: {e}")

# Opcional según tu schema:
PerfilAdmin = None
CountryAdminScope = None
try:
    from reservas.models import PerfilAdmin as _PerfilAdmin
    PerfilAdmin = _PerfilAdmin
except Exception:
    pass

try:
    from reservas.models import CountryAdminScope as _CAS
    CountryAdminScope = _CAS
except Exception:
    pass


@transaction.atomic
def run():
    if PerfilAdmin is None and CountryAdminScope is None:
        raise RuntimeError(
            "No existe ni PerfilAdmin.paises ni CountryAdminScope. "
            "Ajusta el script a tu modelo de alcance por país."
        )

    for email, pais_nombre, password in ADMINS:
        try:
            pais = Pais.objects.get(nombre__iexact=pais_nombre)
        except ObjectDoesNotExist:
            print(f"⚠️  País no encontrado: {pais_nombre}")
            continue

        user, created = U.objects.get_or_create(
            username=email,
            defaults={"email": email},
        )
        # Fuerza datos básicos y contraseña
        user.email = email
        user.is_staff = True
        user.is_active = True
        user.set_password(password)
        user.save()

        # Asignar alcance por país según tu modelo real
        if PerfilAdmin is not None and hasattr(PerfilAdmin, "paises"):
            perfil, _ = PerfilAdmin.objects.get_or_create(user=user)
            perfil.paises.add(pais)
            perfil.save()
        elif CountryAdminScope is not None:
            CountryAdminScope.objects.get_or_create(user=user, pais=pais)
        else:
            raise RuntimeError("No hay forma de asignar alcance por país.")

        print(f"✔ {email} → {pais.nombre}  ({'creado' if created else 'actualizado'}, password aplicada)")

    print("\n🎯 Todos los administradores fueron actualizados correctamente.")


if __name__ == "__main__":
    run()
