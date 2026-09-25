export interface Postulante {
  id: number;
  nombres: string;
  apellidos: string;
  cedula: string;
  estatura_cm: number;
  fecha_nacimiento: string;
  telefono: string;
  correo: string;
  genero: 'M' | 'F' | 'OTRO';
  foto: string;
  sede: string | null;
  creado_en: string;
}

export interface ResultadoVerificacion {
  verificado: boolean;
  motivo?: 'no_se_detecto_rostro' | 'sin_coincidencia';
  confianza?: number | null;
  ya_registrado?: boolean;
  postulante?: Postulante;
  verificado_en?: string;
}

export interface ResultadoManual {
  verificado: boolean;
  ya_registrado: boolean;
  metodo: 'MANUAL';
  forzado_por: string | null;
  postulante: Postulante;
  verificado_en: string;
}

export interface FilaAsistencia {
  id: number;
  postulante_cedula: string;
  postulante_nombres: string;
  postulante_apellidos: string;
  postulante_foto: string;
  sede: string;
  metodo: 'AUTO' | 'MANUAL';
  confianza: number | null;
  verificado_en: string;
}

/** Filtros combinables del dashboard — se mandan igual a la lista, al resumen
 * (gráficos) y a la exportación, para que las 3 vistas sean consistentes. */
export interface FiltrosAsistencia {
  q?: string;
  desde?: string;
  hasta?: string;
  metodo?: 'AUTO' | 'MANUAL' | '';
}

export interface ResumenAsistencias {
  por_sede: { sede: string; total: number }[];
  por_hora: { hora: string; total: number }[];
  por_metodo: { metodo: string; total: number }[];
}
