from django.core.exceptions import ValidationError
from django.test import SimpleTestCase

from asistencia.validators import validar_cedula_ecuatoriana


class ValidarCedulaEcuatorianaTest(SimpleTestCase):
    def test_acepta_cedula_valida(self):
        validar_cedula_ecuatoriana("1710034065")  # no debe lanzar

    def test_rechaza_digito_verificador_incorrecto(self):
        with self.assertRaises(ValidationError):
            validar_cedula_ecuatoriana("1234567890")

    def test_rechaza_longitud_incorrecta(self):
        with self.assertRaises(ValidationError):
            validar_cedula_ecuatoriana("12345")

    def test_rechaza_no_numerico(self):
        with self.assertRaises(ValidationError):
            validar_cedula_ecuatoriana("17100340ab")

    def test_rechaza_provincia_invalida(self):
        with self.assertRaises(ValidationError):
            validar_cedula_ecuatoriana("9910034068")

    def test_rechaza_tercer_digito_fuera_de_rango(self):
        with self.assertRaises(ValidationError):
            validar_cedula_ecuatoriana("1760034069")
