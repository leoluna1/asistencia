import { Component, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatCardModule } from '@angular/material/card';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatSelectModule } from '@angular/material/select';
import { CameraCapture } from '../../shared/camera-capture/camera-capture';
import { PostulantesService } from '../../core/postulantes.service';
import { primerMensajeDeError } from '../../core/errores';

@Component({
  selector: 'app-registro',
  standalone: true,
  imports: [
    FormsModule,
    MatButtonModule,
    MatCardModule,
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
  fecha_nacimiento = '';
  telefono = '';
  correo = '';
  genero = '';
  password = '';

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

  get datosCompletos(): boolean {
    return !!(
      this.nombres &&
      this.apellidos &&
      this.cedula &&
      this.estatura_cm &&
      this.fecha_nacimiento &&
      this.telefono &&
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
        fecha_nacimiento: this.fecha_nacimiento,
        telefono: this.telefono,
        correo: this.correo,
        genero: this.genero,
        foto: this.foto()!,
        password: this.password
      });
      this.exito.set(true);
      this.nombres = this.apellidos = this.cedula = '';
      this.fecha_nacimiento = this.telefono = this.correo = this.genero = this.password = '';
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
