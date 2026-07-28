import type {
  FavoriteFilters,
  PlanHistoryEntry,
  PlanRequest,
  PlanResponse,
} from "./types";

// El historial vive en localStorage particionado por uid. Cada usuario (y el
// usuario anónimo) tiene su propio key, así no hay leak cross-user en el mismo
// browser cuando se desloguean o cambian de cuenta.
const KEY_PREFIX = "horarios:plan-history";
const MAX_ENTRIES = 10;

function keyFor(uid: string | null | undefined): string {
  return `${KEY_PREFIX}:${uid || "anon"}`;
}

export function loadHistory(uid: string | null | undefined): PlanHistoryEntry[] {
  try {
    const raw = localStorage.getItem(keyFor(uid));
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

function save(uid: string | null | undefined, entries: PlanHistoryEntry[]) {
  const key = keyFor(uid);
  let toSave = entries.slice(0, MAX_ENTRIES);
  while (toSave.length > 0) {
    try {
      localStorage.setItem(key, JSON.stringify(toSave));
      return;
    } catch {
      // Quota exceeded: drop oldest and retry.
      toSave = toSave.slice(0, -1);
    }
  }
}

export function pushHistory(
  uid: string | null | undefined,
  input: {
    request: PlanRequest;
    filters: FavoriteFilters;
    response: PlanResponse;
  }
): PlanHistoryEntry[] {
  const list = loadHistory(uid);
  const sig = JSON.stringify(input.request);
  const prevSig = list[0] ? JSON.stringify(list[0].request) : null;
  const entry: PlanHistoryEntry = {
    id:
      typeof crypto !== "undefined" && "randomUUID" in crypto
        ? crypto.randomUUID()
        : String(Date.now()) + Math.random().toString(36).slice(2),
    createdAt: Date.now(),
    request: input.request,
    filters: input.filters,
    response: input.response,
  };
  const next = sig === prevSig ? [entry, ...list.slice(1)] : [entry, ...list];
  save(uid, next);
  return next;
}

export function removeHistory(
  uid: string | null | undefined,
  id: string
): PlanHistoryEntry[] {
  const next = loadHistory(uid).filter((e) => e.id !== id);
  save(uid, next);
  return next;
}

export function clearHistory(uid: string | null | undefined) {
  localStorage.removeItem(keyFor(uid));
}

// Replica la lógica del backend (_request_uses_filters): detecta si una entrada
// usa filtros Pro. Días excluidos y solo_con_cupos son gratis.
export function entryUsesProFilters(entry: PlanHistoryEntry): boolean {
  const f = entry.filters;
  if (f.franjas_excluidas && f.franjas_excluidas.length > 0) return true;
  if (f.sedes_permitidas && f.sedes_permitidas.length > 0) return true;
  if (f.max_bache_horas != null) return true;
  if (f.min_dias_semana != null || f.max_dias_semana != null) return true;
  if (f.min_horas_dia != null || f.max_horas_dia != null) return true;
  for (const m of f.materias) {
    if (m.profesores !== null) return true;
    if (m.sede) return true;
    // En materias anuales cátedra y comisión son gratis. Las entradas viejas del
    // historial no traen el flag: sin él se asume no anual, que es lo conservador.
    if (m.anual) continue;
    if (m.catedra_id !== null) return true;
    if (m.comision_codigo) return true;
  }
  return false;
}

export function seleccionUsesProFilters(
  materias: Array<{
    catedra_id: number | null;
    profesores: string[] | null;
    sede?: string | null;
    comision_codigo?: string | null;
    anual?: boolean;
  }>,
  franjas: Array<unknown>,
  sedesPermitidas: string[],
  maxBacheHoras: number | null,
  minDiasSemana: number | null = null,
  maxDiasSemana: number | null = null,
  minHorasDia: number | null = null,
  maxHorasDia: number | null = null
): boolean {
  if (franjas.length > 0) return true;
  if (sedesPermitidas.length > 0) return true;
  if (maxBacheHoras != null) return true;
  if (minDiasSemana != null || maxDiasSemana != null) return true;
  if (minHorasDia != null || maxHorasDia != null) return true;
  for (const m of materias) {
    if (m.profesores !== null) return true;
    if (m.sede) return true;
    if (m.anual) continue;
    if (m.catedra_id !== null) return true;
    if (m.comision_codigo) return true;
  }
  return false;
}
