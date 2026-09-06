import { Component, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatCardModule } from '@angular/material/card';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { CameraCapture } from '../../shared/camera-capture/camera-capture';
import { PostulantesService } from '../../core/postulantes.service';

@Component({
  selector: 'app-registro',
  standalone: true,
  imports: [
    FormsModule,
    MatButtonModule,
    MatCardModule,
    MatFormFieldModule,
    MatInputModule,
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
  sede = '';

  readonly foto = signal<Blob | null>(null);
  readonly fotoPreview = signal<string | null>(null);
  readonly enviando = signal(false);
  readonly error = signal<string | null>(null);
  readonly exito = signal(false);

  constructor(private postulantes: PostulantesService) {}

  onFotoCapturada(foto: Blob): void {
    this.foto.set(foto);
    this.fotoPreview.set(URL.createObjectURL(foto));
  }

  get formCompleto(): boolean {
    return !!(
      this.nombres &&
      this.apellidos &&
      this.cedula &&
      this.estatura_cm &&
      this.sede &&
      this.foto()
    );
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
        sede: this.sede,
        foto: this.foto()!
      });
      this.exito.set(true);
      this.nombres = this.apellidos = this.cedula = this.sede = '';
      this.estatura_cm = null;
      this.foto.set(null);
      this.fotoPreview.set(null);
    } catch (e: any) {
      const detalle = e?.error && JSON.stringify(e.error);
      this.error.set(detalle || 'No se pudo registrar al postulante.');
    } finally {
      this.enviando.set(false);
    }
  }
}
