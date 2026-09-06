import { Component, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { MatButtonModule } from '@angular/material/button';
import { MatCardModule } from '@angular/material/card';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { AuthService } from '../../core/auth.service';

@Component({
  selector: 'app-login',
  standalone: true,
  imports: [FormsModule, MatButtonModule, MatCardModule, MatFormFieldModule, MatInputModule],
  templateUrl: './login.html',
  styleUrl: './login.scss'
})
export class Login {
  username = '';
  password = '';
  readonly cargando = signal(false);
  readonly error = signal<string | null>(null);

  constructor(
    private auth: AuthService,
    private router: Router
  ) {}

  async ingresar(): Promise<void> {
    this.cargando.set(true);
    this.error.set(null);
    try {
      await this.auth.login(this.username, this.password);
      this.router.navigate(['/dashboard']);
    } catch {
      this.error.set('Usuario o contraseña incorrectos.');
    } finally {
      this.cargando.set(false);
    }
  }
}
