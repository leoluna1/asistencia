import { Component, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';
import { MatButtonModule } from '@angular/material/button';
import { MatCardModule } from '@angular/material/card';
import { MatDatepickerModule } from '@angular/material/datepicker';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatSelectModule } from '@angular/material/select';
import { CameraCapture } from '../../shared/camera-capture/camera-capture';
import { InlineMessage } from '../../shared/inline-message/inline-message';
import { AuthService } from '../../core/auth.service';
import { PostulantesService } from '../../core/postulantes.service';
import { primerMensajeDeError } from '../../core/errores';
import { cedulaEcuatorianaValida, soloDigitos } from '../../core/validators';

@Component({
  selector: 'app-registro',
  standalone: true,
  imports: [
    FormsModule,
    RouterLink,
    MatButtonModule,
    MatCardModule,
    MatDatepickerModule,
    MatIconModule,
    MatFormFieldModule,
    MatInputModule,
    MatProgressSpinnerModule,
    MatSelectModule,
    CameraCapture,
    InlineMessage
  ],
  templateUrl: './registro.html',
  styleUrl: './registro.scss'
})
export class Registro {
  nombres = '';
  apellidos = '';
  cedula = '';
  estatura_cm: number | null = null;
  fechaNacimiento: Date | null = null;
  telefono = '';
  correo = '';
  genero = '';
  password = '';

  // Sanity del selector de fecha, no una regla de negocio de elegibilidad (esa la
  // define la convocatoria, no este formulario): evita años absurdos por un toque
  // accidental, nada más.
  readonly hoy = new Date();
  readonly fechaMaxima = new Date(this.hoy.getFullYear() - 16, this.hoy.getMonth(), this.hoy.getDate());
  readonly fechaMinima = new Date(this.hoy.getFullYear() - 100, this.hoy.getMonth(), this.hoy.getDate());

  // 'datos' primero, sin tocar la cámara — recién en 'foto' se llama a
  // getUserMedia (dentro de <app-camera-capture>), para no pedir permiso de
  // cámara mientras la persona todavía está llenando el formulario. 'codigo':
  // la cuenta queda inactiva hasta confirmar el correo (ver VerificarCorreoView).
  readonly paso = signal<'datos' | 'foto' | 'codigo'>('datos');

  readonly foto = signal<Blob | null>(null);
  readonly fotoPreview = signal<string | null>(null);
  readonly enviando = signal(false);
  readonly error = signal<string | null>(null);
  readonly errorEsCuentaDuplicada = signal(false);

  codigoIngresado = '';
  readonly verificando = signal(false);
  readonly errorCodigo = signal<string | null>(null);
  readonly reenviando = signal(false);
  readonly codigoReenviado = signal(false);

  constructor(
    private postulantes: PostulantesService,
    private auth: AuthService,
    private router: Router
  ) {}

  // Escribe el valor filtrado directo en el <input>: si el resultado filtrado
  // coincide con el valor previo del modelo (ej. se pegó texto con dígitos de más
  // al final), Angular no vuelve a sincronizar la vista por sí solo y quedarían
  // caracteres de más visibles aunque el modelo ya esté bien cortado.
  onCedulaInput(event: Event): void {
    const input = event.target as HTMLInputElement;
    this.cedula = soloDigitos(input.value, 10);
    input.value = this.cedula;
  }

  onTelefonoInput(event: Event): void {
    const input = event.target as HTMLInputElement;
    this.telefono = soloDigitos(input.value, 10);
    input.value = this.telefono;
  }

  /** Solo se muestra cuando ya hay 10 dígitos — mientras se escribe no molesta. */
  get cedulaInvalida(): boolean {
    return this.cedula.length === 10 && !cedulaEcuatorianaValida(this.cedula);
  }

  private get fechaNacimientoISO(): string {
    if (!this.fechaNacimiento) return '';
    const y = this.fechaNacimiento.getFullYear();
    const m = String(this.fechaNacimiento.getMonth() + 1).padStart(2, '0');
    const d = String(this.fechaNacimiento.getDate()).padStart(2, '0');
    return `${y}-${m}-${d}`;
  }

  get datosCompletos(): boolean {
    return !!(
      this.nombres &&
      this.apellidos &&
      this.cedula.length === 10 &&
      !this.cedulaInvalida &&
      this.estatura_cm &&
      this.fechaNacimiento &&
      this.telefono.length === 10 &&
      this.correo &&
      this.genero &&
      this.password
    );
  }

  continuarAFoto(): void {
    if (this.datosCompletos) this.paso.set('foto');
  }

  onFotoCapturada(foto: Blob): void {
    this.foto.set(foto);
    this.fotoPreview.set(URL.createObjectURL(foto));
  }

  retomarFoto(): void {
    this.foto.set(null);
    this.fotoPreview.set(null);
    this.error.set(null);
    this.errorEsCuentaDuplicada.set(false);
  }

  get formCompleto(): boolean {
    return this.datosCompletos && !!this.foto();
  }

  async registrar(): Promise<void> {
    if (!this.formCompleto) return;
    this.enviando.set(true);
    this.error.set(null);
    try {
      await this.postulantes.registrar({
        nombres: this.nombres,
        apellidos: this.apellidos,
        cedula: this.cedula,
        estatura_cm: this.estatura_cm!,
        fecha_nacimiento: this.fechaNacimientoISO,
        telefono: this.telefono,
        correo: this.correo,
        genero: this.genero,
        foto: this.foto()!,
        password: this.password
      });
    } catch (e: any) {
      this.error.set(primerMensajeDeError(e?.error) || 'No se pudo registrar al postulante.');
      // Se mira la presencia del campo puntual en el error (no el texto del
      // mensaje, frágil): "¿ya tenés cuenta?" solo aplica cuando el motivo del
      // rechazo es justo una cédula o un correo ya registrados.
      this.errorEsCuentaDuplicada.set(!!(e?.error?.cedula || e?.error?.correo));
      return;
    } finally {
      this.enviando.set(false);
    }
    // La cuenta queda inactiva hasta confirmar el correo (ver
    // VerificarCorreoView) — antes esto logueaba directo, pero el cliente pidió
    // que primero se confirme que el correo es real.
    this.paso.set('codigo');
  }

  async verificarCodigo(): Promise<void> {
    if (!this.codigoIngresado) return;
    this.verificando.set(true);
    this.errorCodigo.set(null);
    try {
      await this.postulantes.verificarCorreo(this.cedula, this.codigoIngresado);
      // Recién acá se loguea — con la misma clave que ya escribió — y se lo
      // manda a su panel, que sirve de confirmación de que todo funcionó.
      await this.auth.login(this.cedula, this.password);
      this.router.navigate(['/mi-postulante']);
    } catch (e: any) {
      this.errorCodigo.set(primerMensajeDeError(e?.error) || 'No se pudo verificar el código.');
    } finally {
      this.verificando.set(false);
    }
  }

  async reenviarCodigo(): Promise<void> {
    this.reenviando.set(true);
    this.errorCodigo.set(null);
    this.codigoReenviado.set(false);
    try {
      await this.postulantes.reenviarCodigo(this.cedula);
      this.codigoReenviado.set(true);
    } catch (e: any) {
      this.errorCodigo.set(primerMensajeDeError(e?.error) || 'No se pudo reenviar el código.');
    } finally {
      this.reenviando.set(false);
    }
  }
}
