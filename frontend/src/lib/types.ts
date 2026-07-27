export type TipoCurso = "teorico" | "seminario" | "comision";

export interface MateriaListItem {
  codigo: number;
  nombre: string;
  // Total histórico, incluye cátedras que ya no se dictan. Lo usa el buscador
  // de reseñas, que debe seguir encontrando materias discontinuadas.
  cant_catedras: number;
  // Las que se dictan este cuatrimestre. En 0 la materia no se ofrece y se
  // oculta del selector del armador de planes. Siempre presente: las requests
  // llevan `?v=DATA_VERSION`, así que nunca se sirve un payload viejo (ver api.ts).
  cant_catedras_vigentes: number;
}

export interface CursoSummary {
  id: number;
  tipo: TipoCurso | string;
  codigo: string;
  dia: string | null;
  hora_inicio: string | null;
  hora_fin: string | null;
  aula: string | null;
}

export interface CursoEnPlan extends CursoSummary {
  catedra_id: number;
  profesor: string | null;
  sede: string | null;
  vacantes?: number | null;
}

export interface OpcionMateria {
  materia_codigo: number;
  materia_nombre: string;
  catedra_id: number;
  catedra_numero: string | null;
  catedra_titular: string | null;
  cursos: CursoEnPlan[];
}

export interface Plan {
  opciones: OpcionMateria[];
}

export interface FranjaExcluida {
  dias: string[];
  hora_inicio: string; // "HH:MM"
  hora_fin: string;
}

export interface MateriaSeleccionada {
  codigo: number;
  catedra_id: number | null;
  // null = todos (sin filtro). [] = ninguno (sin opciones para esa materia).
  // Lista no vacía = subset explícito.
  profesores: string[] | null;
  // Sede específica para esta materia. Hace override de sedes_permitidas general.
  sede?: string | null;
}

export interface PlanRequest {
  materias: MateriaSeleccionada[];
  dias_excluidos?: string[];
  franjas_excluidas?: FranjaExcluida[];
  sedes_permitidas?: string[];
  max_bache_horas?: number | null;
  min_dias_semana?: number | null;
  max_dias_semana?: number | null;
  min_horas_dia?: number | null;
  max_horas_dia?: number | null;
  max_planes?: number;
  solo_con_cupos?: boolean;
}

export interface ComisionOpcion {
  profesor: string | null;
  sede: string | null;
}

export interface CatedraOpcion {
  id: number;
  numero: string | null;
  titular: string | null;
  cuatrimestre: string | null;
  // Se dicta este cuatrimestre. El endpoint devuelve vigentes y no vigentes:
  // el armador de planes filtra, el diálogo de reseñas a propósito no.
  vigente: boolean;
  profesores: string[];
  comisiones: ComisionOpcion[];
  // Reseñas de la cátedra (para mostrar estrellas en el selector del planner).
  avg_rating: number | null;
  review_count: number;
}

export interface ProfesorRating {
  avg_rating: number | null;
  review_count: number;
}

export interface MateriaOpciones {
  codigo: number;
  nombre: string;
  catedras: CatedraOpcion[];
  // Promedio por profesor (clave = nombre) para mostrar estrella + nota.
  profesores_rating: Record<string, ProfesorRating>;
}

export interface PlanResponse {
  planes: Plan[];
  total_generados: number;
  materias_sin_opciones: number[];
}

export interface FavoriteFilters {
  dias_excluidos: string[];
  franjas_excluidas: FranjaExcluida[];
  sedes_permitidas: string[];
  max_bache_horas?: number | null;
  min_dias_semana?: number | null;
  max_dias_semana?: number | null;
  min_horas_dia?: number | null;
  max_horas_dia?: number | null;
  solo_con_cupos?: boolean;
  materias: Array<{
    codigo: number;
    nombre: string;
    catedra_id: number | null;
    catedra_label: string | null;
    profesores: string[] | null;
    sede?: string | null;
  }>;
}

export interface PlanHistoryEntry {
  id: string;
  createdAt: number;
  request: PlanRequest;
  filters: FavoriteFilters;
  response: PlanResponse;
}

export interface Favorite {
  id: number;
  plan: Plan;
  filters: FavoriteFilters | null;
  created_at: string;
}

export const DIAS = [
  "lunes",
  "martes",
  "miercoles",
  "jueves",
  "viernes",
  "sabado",
] as const;

export interface Carrera {
  slug: string;
  nombre: string;
  sedes: string[];
}

export interface UserProfile {
  carrera: string | null;
  nombre: string | null;
}

export interface SubscriptionState {
  active: boolean;
  valid_until: string | null;
}

export interface Me {
  carrera: string | null;
  nombre: string | null;
  subscription: SubscriptionState;
}

// --- Reseñas de cátedras ------------------------------------------------------

export type ReviewSort = "mejores" | "peores" | "mas_resenas" | "materia";

export interface CatedraRankItem {
  catedra_id: number;
  materia_codigo: number;
  materia_nombre: string;
  numero: string | null;
  titular: string | null;
  cuatrimestre: string | null;
  avg_rating: number | null;
  review_count: number;
}

export interface CatedraRankPage {
  items: CatedraRankItem[];
  total: number;
  page: number;
  page_size: number;
}

export interface ReviewItem {
  id: number;
  // Nota de la cátedra.
  rating: number;
  comment: string | null;
  // Profesor puntuado y su nota, opcionales (o los dos o ninguno).
  profesor: string | null;
  profesor_rating: number | null;
  anio: number;
  created_at: string;
  updated_at: string;
}

export interface ProfesorStats {
  profesor: string;
  avg_rating: number | null;
  review_count: number;
}

export interface CatedraHeader {
  id: number;
  materia_codigo: number;
  materia_nombre: string;
  numero: string | null;
  titular: string | null;
  cuatrimestre: string | null;
}

export interface CatedraReviewsResponse {
  catedra: CatedraHeader;
  avg_rating: number | null;
  review_count: number;
  // Claves "1".."5" (JSON serializa las claves numéricas como string).
  distribution: Record<string, number>;
  // Todos los profesores de la cátedra con sus agregados (no filtrado).
  profesores: ProfesorStats[];
  my_review: ReviewItem | null;
  reviews: ReviewItem[];
  total: number;
  page: number;
  page_size: number;
  // True cuando la lista se recortó por el gate free (hay más reseñas ocultas).
  locked: boolean;
}

export const DEFAULT_CARRERA = "licenciatura-psicologia";

export const SEDES: Array<{ codigo: string; nombre: string }> = [
  { codigo: "HY", nombre: "Hipólito Yrigoyen" },
  { codigo: "IN", nombre: "Independencia" },
  { codigo: "SI", nombre: "San Isidro" },
  { codigo: "AV", nombre: "Avellaneda" },
  { codigo: "EC", nombre: "Eco" },
];
