"""
Repara columnas "huérfanas": columnas que existen en la base de datos pero ya no en el código
(p. ej. reservas_mesa.reservable, agregada a mano en algún momento). Si son NOT NULL y no tienen
valor por defecto, cualquier INSERT desde Django falla. Esta migración NO borra datos:
solo les quita la obligatoriedad (y a 'reservable' le pone por defecto TRUE).
"""
from django.db import migrations


def reparar(apps, schema_editor):
    conn = schema_editor.connection
    if conn.vendor != "postgresql":
        return
    app = apps.get_app_config("reservas")
    with conn.cursor() as cur:
        for model in app.get_models():
            tabla = model._meta.db_table
            conocidas = {f.column for f in model._meta.concrete_fields}
            cur.execute(
                """
                SELECT column_name, column_default FROM information_schema.columns
                WHERE table_schema = current_schema() AND table_name = %s AND is_nullable = 'NO'
                """,
                [tabla],
            )
            for col, default in cur.fetchall():
                if col in conocidas or default is not None:
                    continue
                q = conn.ops.quote_name
                if col == "reservable":
                    cur.execute(f"ALTER TABLE {q(tabla)} ALTER COLUMN {q(col)} SET DEFAULT TRUE")
                else:
                    cur.execute(f"ALTER TABLE {q(tabla)} ALTER COLUMN {q(col)} DROP NOT NULL")


class Migration(migrations.Migration):
    dependencies = [("reservas", "0048_lista_espera")]
    operations = [migrations.RunPython(reparar, migrations.RunPython.noop)]
