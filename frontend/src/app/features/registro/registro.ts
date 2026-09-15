import { Component, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatCardModule } from '@angular/material/card';
import { MatDatepickerModule } from '@angular/material/datepicker';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatSelectModule } from '@angular/material/select';
import { CameraCapture } from '../../shared/camera-capture/camera-capture';
import { PostulantesService } from '../../core/postulantes.service';
import { primerMensajeDeError } from '../../core/errores';
import { cedulaEcuatorianaValida, soloDigitos } from '../../core/validators';

@Component({
  selector: 'app-registro',
  standalone: true,
  imports: [
    FormsModule,
    MatButtonModule,
    MatCardModule,
    MatDatepickerModule,
    MatFormFieldModule,
    MatInputModule,
    MatSelectModule,
    CameraCapture
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
  // cámara mientras la persona todavía está llenando el formulario.
  readonly paso = signal<'datos' | 'foto'>('datos');

  readonly foto = signal<Blob | null>(null);
  readonly fotoPreview = signal<string | null>(null);
  readonly enviando = signal(false);
  readonly error = signal<string | null>(null);
  readonly exito = signal(false);

  constructor(private postulantes: PostulantesService) {}

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
  }

  get formCompleto(): boolean {
    return this.datosCompletos && !!this.foto();
  }

  async registrar(): Promise<void> {
    if (!this.formCompleto) return;
    this.enviando.set(true);
    this.error.set(null);
    this.exito.set(false);
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
      this.exito.set(true);
      this.nombres = this.apellidos = this.cedula = '';
      this.telefono = this.correo = this.genero = this.password = '';
      this.fechaNacimiento = null;
      this.estatura_cm = null;
      this.foto.set(null);
      this.fotoPreview.set(null);
      this.paso.set('datos');
    } catch (e: any) {
      this.error.set(primerMensajeDeError(e?.error) || 'No se pudo registrar al postulante.');
    } finally {
      this.enviando.set(false);
    }
  }
}
