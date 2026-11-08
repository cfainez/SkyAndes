from django.core.management.base import BaseCommand

from skyandes.services import liberar_bloqueos_expirados


class Command(BaseCommand):
    help = (
        "Libera los asientos cuyo bloqueo de 10 minutos venció y expira las "
        "reservas pendientes de pago asociadas (RN-04/RN-06)."
    )

    def handle(self, *args, **options):
        resultado = liberar_bloqueos_expirados()
        self.stdout.write(
            self.style.SUCCESS(
                "Reservas expiradas: {reservas_expiradas} | "
                "Asientos liberados: {asientos_liberados}".format(**resultado)
            )
        )
