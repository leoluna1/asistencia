from django.core.exceptions import ValidationError

# Algoritmo oficial de cédula ecuatoriana (módulo 10, coeficientes del INEC).
_COEFICIENTES = (2, 1, 2, 1, 2, 1, 2, 1, 2)


def validar_cedula_ecuatoriana(cedula: str) -> None:
    if not cedula.isdigit() or len(cedula) != 10:
        raise ValidationError("La cédula debe tener 10 dígitos.")

    provincia = int(cedula[0:2])
    tercer_digito = int(cedula[2])
    if not (1 <= provincia <= 24) or tercer_digito >= 6:
        raise ValidationError("La cédula no tiene un formato válido.")

    total = 0
    for digito, coeficiente in zip(cedula[:9], _COEFICIENTES):
        producto = int(digito) * coeficiente
        total += producto - 9 if producto > 9 else producto

    verificador = (10 - total % 10) % 10
    if verificador != int(cedula[9]):
        raise ValidationError("La cédula no es válida (dígito verificador incorrecto).")
