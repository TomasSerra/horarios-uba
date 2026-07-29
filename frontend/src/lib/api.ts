import type {
  Carrera,
  CatedraRankPage,
  CatedraReviewsResponse,
  Favorite,
  FavoriteFilters,
  MateriaListItem,
  MateriaOpciones,
  Me,
  Plan,
  PlanRequest,
  PlanResponse,
  ReviewItem,
  ReviewSort,
  UserProfile,
} from "./types";
import { reportError } from "./reportError";

export const API_BASE = import.meta.env.VITE_API_URL || "http://localhost:8000";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
    this.name = "ApiError";
  }
}

// Reintentamos ante fallos de red (fetch tira → no es ApiError) o errores
// transitorios del servidor (5xx / 429). Nunca ante 4xx: un 403 (Pro gating) o
// un 400 (validación) no se arregla repitiendo.
function isRetryable(e: unknown): boolean {
  if (e instanceof ApiError) return e.status >= 500 || e.status === 429;
  return true;
}

const delay = (ms: number) => new Promise((r) => setTimeout(r, ms));

async function request<T>(
  path: string,
  init?: RequestInit,
  token?: string | null
): Promise<T> {
  const doFetch = async (): Promise<T> => {
    const headers: Record<string, string> = {
      "Content-Type": "application/json",
      ...((init?.headers as Record<string, string>) || {}),
    };
    if (token) headers.Authorization = `Bearer ${token}`;
    const res = await fetch(`${API_BASE}${path}`, { ...init, headers });
    if (!res.ok) {
      let detail = res.statusText;
      try {
        const body = await res.json();
        detail = body.detail || detail;
      } catch {
        /* ignore */
      }
      // Mantener el formato "${status} ${detail}" en el mensaje: Home.tsx
      // detecta el 403 con msg.startsWith("403").
      throw new ApiError(res.status, `${res.status} ${detail}`);
    }
    return res.json() as Promise<T>;
  };

  // Un único reintento automático antes de propagar el error a la UI.
  try {
    return await doFetch();
  } catch (e) {
    if (isRetryable(e)) {
      await delay(400);
      try {
        return await doFetch();
      } catch (e2) {
        reportApiFailure(path, e2);
        throw e2;
      }
    }
    // 4xx no reintentable: esperable (403 paywall, 404, etc.), no se reporta.
    throw e;
  }
}

// Reporta a Vercel Logs los fallos que el backend nunca ve (red/CORS/timeout) o
// los 5xx que ya sobrevivieron al reintento. Los 4xx no se reportan.
function reportApiFailure(path: string, e: unknown): void {
  const isServerError = e instanceof ApiError && e.status >= 500;
  const isNetworkError = !(e instanceof ApiError);
  if (!isServerError && !isNetworkError) return;
  reportError({
    kind: "api",
    message: `${API_BASE}${path} → ${e instanceof Error ? e.message : String(e)}`,
    name: e instanceof Error ? e.name : "ApiError",
    stack: e instanceof Error ? e.stack : null,
  });
}

export interface CheckoutResponse {
  init_point: string;
  external_reference: string;
}

export interface PagoStatus {
  status: "pending" | "approved";
}

// Cache de listMaterias en localStorage: el scraper corre diario, los datos
// son estables. Evita pegarle al BE cada vez que se monta el selector.
const MATERIAS_TTL_MS = 60 * 60 * 1000;

// Versión de los datos del catálogo (carreras / materias / opciones). Cumple
// dos funciones:
//   1. invalida el cache de localStorage (se guarda junto al payload), y
//   2. viaja como `?v=` en la URL de los GETs cacheables, así un deploy del FE
//      cambia la URL y saltea el cache HTTP del browser y del CDN al instante.
//
// Sin (2) no alcanza con bumpear la versión: el refetch pega contra la misma URL
// y el browser devuelve el body viejo (Cache-Control de _set_static_cache), que
// puede no tener campos que el FE ya da por hechos.
//
// BUMPEAR cuando: cambie el shape de estos payloads, o cuando haga falta que los
// usuarios vean datos nuevos ya mismo.
//
// En particular, al arrancar un cuatrimestre el orden correcto es
// **scraper primero, bump + deploy del FE después**. Al revés queda cacheado el
// snapshot previo al sweep: trae el campo de vigencia (así que `fetchFresco` lo
// da por bueno) pero con todas las cátedras todavía vigentes.
export const DATA_VERSION = 8;

function withVersion(path: string): string {
  return `${path}${path.includes("?") ? "&" : "?"}v=${DATA_VERSION}`;
}

const MATERIAS_CACHE_VERSION = DATA_VERSION;

// Red de seguridad sobre el `?v=`: si igual llega un payload viejo (bundle sin
// recargar, proxy que ignora la query, CDN raro), reintenta salteando el cache
// HTTP en vez de dejar que el FE filtre contra un campo `undefined` — que se
// vería como "no hay materias" en lugar de como un error.
async function fetchFresco<T>(path: string, estaCompleto: (d: T) => boolean) {
  const data = await request<T>(path);
  if (estaCompleto(data)) return data;
  return request<T>(path, { cache: "reload" });
}

function readMateriasCache(key: string): MateriaListItem[] | null {
  try {
    const raw = localStorage.getItem(key);
    if (!raw) return null;
    const { data, expires, version } = JSON.parse(raw);
    if (version !== MATERIAS_CACHE_VERSION) return null;
    if (typeof expires !== "number" || expires < Date.now()) return null;
    // Puede haber quedado guardado un payload viejo bajo la versión actual (se
    // escribió antes de que existiera el chequeo de shape). Si le faltan los
    // campos de vigencia o anualidad lo descartamos: mejor un refetch que un
    // selector vacío o un filtro Pro mal gateado.
    if (
      data.length > 0 &&
      (data[0].cant_catedras_vigentes === undefined ||
        data[0].anual === undefined)
    ) {
      return null;
    }
    return data as MateriaListItem[];
  } catch {
    return null;
  }
}

function writeMateriasCache(key: string, data: MateriaListItem[]): void {
  try {
    localStorage.setItem(
      key,
      JSON.stringify({
        data,
        expires: Date.now() + MATERIAS_TTL_MS,
        version: MATERIAS_CACHE_VERSION,
      })
    );
  } catch {
    /* localStorage lleno o deshabilitado: degradamos silenciosamente */
  }
}

export const api = {
  listCarreras: () => request<Carrera[]>(withVersion("/carreras")),
  // Filtro por nombre ocurre client-side en MateriaSelector vía cmdk; acá solo
  // cacheamos el listado completo (con TTL) por carrera.
  listMateriasCached: async (carrera?: string): Promise<MateriaListItem[]> => {
    const key = `materias:${carrera ?? "all"}`;
    const cached = readMateriasCache(key);
    if (cached) return cached;
    const data = await fetchFresco<MateriaListItem[]>(
      withVersion(
        `/materias${carrera ? `?carrera=${encodeURIComponent(carrera)}` : ""}`
      ),
      (d) =>
        d.length === 0 ||
        (d[0].cant_catedras_vigentes !== undefined && d[0].anual !== undefined)
    );
    writeMateriasCache(key, data);
    return data;
  },
  getMateriaOpciones: (codigo: number) =>
    fetchFresco<MateriaOpciones>(
      withVersion(`/materias/${codigo}/opciones`),
      (d) =>
        d.catedras.length === 0 ||
        (d.catedras[0].vigente !== undefined &&
          (d.catedras[0].comisiones.length === 0 ||
            d.catedras[0].comisiones[0].codigo !== undefined))
    ),
  getMe: (token: string) => request<Me>("/me", undefined, token),
  updateProfile: (
    body: { carrera?: string; nombre?: string },
    token: string
  ) =>
    request<UserProfile>(
      "/me/profile",
      { method: "PATCH", body: JSON.stringify(body) },
      token
    ),
  postPlanes: (req: PlanRequest, token?: string | null) =>
    request<PlanResponse>(
      "/planes",
      { method: "POST", body: JSON.stringify(req) },
      token ?? undefined
    ),
  postCheckout: (token: string, flow: "redirect" | "qr" = "redirect") =>
    request<CheckoutResponse>(
      "/pagos/checkout",
      { method: "POST", body: JSON.stringify({ flow }) },
      token
    ),
  getPagoStatus: (externalReference: string) =>
    request<PagoStatus>(`/pagos/${externalReference}/status`),
  listFavoritos: (token: string) =>
    request<{ favorites: Favorite[] }>("/favoritos", undefined, token),
  addFavorito: (
    plan: Plan,
    filters: FavoriteFilters | null,
    nombre: string,
    descripcion: string | null,
    token: string
  ) =>
    request<{ id: number; created_at: string }>(
      "/favoritos",
      {
        method: "POST",
        body: JSON.stringify({ plan, filters, nombre, descripcion }),
      },
      token
    ),
  updateFavorito: (
    id: number,
    nombre: string,
    descripcion: string | null,
    token: string
  ) =>
    request<{ nombre: string; descripcion: string | null }>(
      `/favoritos/${id}`,
      { method: "PATCH", body: JSON.stringify({ nombre, descripcion }) },
      token
    ),
  deleteFavorito: (id: number, token: string) =>
    request<{ ok: boolean }>(
      `/favoritos/${id}`,
      { method: "DELETE" },
      token
    ),
  listCatedraRankings: (params: {
    carrera: string;
    q?: string;
    sort?: ReviewSort;
    page?: number;
  }) => {
    const qs = new URLSearchParams();
    qs.set("carrera", params.carrera);
    if (params.q) qs.set("q", params.q);
    if (params.sort) qs.set("sort", params.sort);
    if (params.page) qs.set("page", String(params.page));
    return request<CatedraRankPage>(`/catedras?${qs.toString()}`);
  },
  // token opcional: si hay sesión, la respuesta incluye `my_review`.
  // `rating` filtra el listado por cantidad de estrellas (null = todas);
  // `profesor` filtra por profesor (null = todos). Ambos combinan.
  getCatedraReviews: (
    catedraId: number,
    page: number,
    rating: number | null,
    profesor: string | null,
    token?: string | null
  ) => {
    const qs = new URLSearchParams({ page: String(page) });
    if (rating != null) qs.set("rating", String(rating));
    if (profesor != null) qs.set("profesor", profesor);
    return request<CatedraReviewsResponse>(
      `/catedras/${catedraId}/reviews?${qs.toString()}`,
      undefined,
      token ?? undefined
    );
  },
  saveCatedraReview: (
    catedraId: number,
    body: {
      rating: number;
      comment: string | null;
      profesor: string | null;
      profesor_rating: number | null;
      anio: number;
    },
    token: string
  ) =>
    request<ReviewItem>(
      `/catedras/${catedraId}/reviews`,
      { method: "PUT", body: JSON.stringify(body) },
      token
    ),
  deleteCatedraReview: (catedraId: number, token: string) =>
    request<{ ok: boolean }>(
      `/catedras/${catedraId}/reviews`,
      { method: "DELETE" },
      token
    ),
};
