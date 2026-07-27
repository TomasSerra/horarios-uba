import { useEffect, useMemo, useState } from "react";
import {
  ChevronDown,
  X,
  Loader2,
  Users,
  GraduationCap,
  Gem,
  MapPin,
  Star,
} from "lucide-react";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import { StarRating } from "@/components/StarRating";
import { api } from "@/lib/api";
import { useSubscription } from "@/lib/useSubscription";
import { useIsWide } from "@/lib/useIsWide";
import { usePaywall } from "@/lib/paywall";
import { SEDES } from "@/lib/types";
import type {
  CatedraOpcion,
  MateriaOpciones,
  MateriaSeleccionada,
  ProfesorRating,
} from "@/lib/types";

interface Props {
  nombre: string;
  seleccion: MateriaSeleccionada;
  onChange: (s: MateriaSeleccionada) => void;
  onRemove: () => void;
}

export function MateriaCard({ nombre, seleccion, onChange, onRemove }: Props) {
  const { isPaid, isLoading: subLoading } = useSubscription();
  const openPaywall = usePaywall();
  const [opciones, setOpciones] = useState<MateriaOpciones | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    api
      .getMateriaOpciones(seleccion.codigo)
      .then((d) => {
        if (!cancelled) setOpciones(d);
      })
      .catch((e: Error) => {
        if (!cancelled) setError(e.message);
      })
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [seleccion.codigo]);

  // El endpoint devuelve también las cátedras que ya no se dictan (las necesita
  // el diálogo de reseñas). Para armar planes sólo sirven las vigentes, y como
  // los universos de profesor y sede se derivan de acá, filtrar en este único
  // punto alcanza para las tres dimensiones.
  const catedrasVigentes = useMemo(
    () => opciones?.catedras.filter((c) => c.vigente) ?? [],
    [opciones]
  );

  // Filtrado de a tres (cátedra ⇄ profesor ⇄ sede): cada dimensión se acota a
  // lo compatible con las otras dos. La relación profesor↔sede vive en la
  // comisión, así que derivamos todo de la lista plana de comisiones.
  const comisiones = useMemo(() => {
    return catedrasVigentes.flatMap((c) =>
      (c.comisiones ?? []).map((cm) => ({
        catedra_id: c.id,
        profesor: cm.profesor,
        sede: cm.sede,
      }))
    );
  }, [catedrasVigentes]);

  // Universos posibles para esta materia.
  const profesoresUniverse = useMemo(() => {
    const set = new Set<string>();
    comisiones.forEach((c) => c.profesor && set.add(c.profesor));
    return Array.from(set).sort();
  }, [comisiones]);

  const sedesUniverse = useMemo(() => {
    const present = new Set<string>();
    comisiones.forEach((c) => c.sede && present.add(c.sede));
    return SEDES.filter((s) => present.has(s.codigo));
  }, [comisiones]);

  // Disponibles según la selección actual (excluyendo la propia dimensión).
  const catedrasDisponibles = useMemo(() => {
    const set = new Set<number>();
    comisiones.forEach((c) => {
      const okSede = seleccion.sede == null || c.sede === seleccion.sede;
      const okProf =
        seleccion.profesores == null ||
        (c.profesor != null && seleccion.profesores.includes(c.profesor));
      if (okSede && okProf) set.add(c.catedra_id);
    });
    return set;
  }, [comisiones, seleccion.sede, seleccion.profesores]);

  const profesoresDisponibles = useMemo(() => {
    const set = new Set<string>();
    comisiones.forEach((c) => {
      const okCat =
        seleccion.catedra_id == null || c.catedra_id === seleccion.catedra_id;
      const okSede = seleccion.sede == null || c.sede === seleccion.sede;
      if (okCat && okSede && c.profesor) set.add(c.profesor);
    });
    return Array.from(set).sort();
  }, [comisiones, seleccion.catedra_id, seleccion.sede]);

  const sedesDisponibles = useMemo(() => {
    const set = new Set<string>();
    comisiones.forEach((c) => {
      const okCat =
        seleccion.catedra_id == null || c.catedra_id === seleccion.catedra_id;
      const okProf =
        seleccion.profesores == null ||
        (c.profesor != null && seleccion.profesores.includes(c.profesor));
      if (okCat && okProf && c.sede) set.add(c.sede);
    });
    return set;
  }, [comisiones, seleccion.catedra_id, seleccion.profesores]);

  // Una cátedra restaurada desde ?q= o desde el historial puede haber dejado de
  // dictarse. Sin esto el dropdown muestra "Todas" pero igual se postea el id
  // muerto a /planes, que devuelve cero planes con un cartel confuso.
  useEffect(() => {
    if (!opciones) return;
    if (seleccion.catedra_id === null) return;
    if (catedrasVigentes.some((c) => c.id === seleccion.catedra_id)) return;
    onChange({ ...seleccion, catedra_id: null });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [opciones, catedrasVigentes]);

  // Si la cátedra/sede elegida deja profesores seleccionados fuera de lo
  // disponible, los limpio. null = todos (no hay nada que sanitizar).
  useEffect(() => {
    // Sin opciones cargadas no hay disponibles todavía y esto borraría una
    // selección legítima (p. ej. la restaurada desde ?q= al recargar).
    if (!opciones) return;
    if (seleccion.profesores === null) return;
    if (seleccion.profesores.length === 0) return;
    const validos = new Set(profesoresDisponibles);
    const filtrados = seleccion.profesores.filter((p) => validos.has(p));
    if (filtrados.length !== seleccion.profesores.length) {
      onChange({ ...seleccion, profesores: filtrados });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [opciones, profesoresDisponibles]);

  const catedraSeleccionada = catedrasVigentes.find(
    (c) => c.id === seleccion.catedra_id
  );

  // Materia agregada desde una URL o un historial viejos, ya discontinuada.
  const sinOferta = !!opciones && catedrasVigentes.length === 0;

  return (
    <div className="rounded-xl border border-border bg-white p-4">
      <div className="flex items-start justify-between gap-3">
        <h3 className="text-sm font-semibold leading-tight">{nombre}</h3>
        <button
          type="button"
          onClick={onRemove}
          className="rounded-md p-1 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
          title="Quitar materia"
        >
          <X className="size-4" />
        </button>
      </div>

      {loading && (
        <div className="mt-3 flex items-center gap-2 text-xs text-muted-foreground">
          <Loader2 className="size-3.5 animate-spin" />
          Cargando opciones...
        </div>
      )}

      {error && (
        <p className="mt-3 text-xs text-destructive">{error}</p>
      )}

      {sinOferta && (
        <p className="mt-3 text-xs text-amber-700">
          Esta materia no se dicta este cuatrimestre. Quitala para poder generar
          planes.
        </p>
      )}

      {opciones && !sinOferta && (
        <div className="mt-3 grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">
          <div>
            <p className="mb-1 text-xs font-medium text-muted-foreground">
              Cátedra
            </p>
            {subLoading ? (
              <Skeleton className="h-9 w-full rounded-lg" />
            ) : (
              <CatedraDropdown
                catedras={catedrasVigentes}
                disponibles={catedrasDisponibles}
                selected={seleccion.catedra_id}
                onSelect={(id) => onChange({ ...seleccion, catedra_id: id })}
                disabled={!isPaid}
                onLockedClick={() => openPaywall("catedra")}
              />
            )}
          </div>
          <div>
            <p className="mb-1 text-xs font-medium text-muted-foreground">
              Profesores
            </p>
            {subLoading ? (
              <Skeleton className="h-9 w-full rounded-lg" />
            ) : (
              <ProfesoresDropdown
                profesores={profesoresUniverse}
                disponibles={profesoresDisponibles}
                ratings={opciones.profesores_rating}
                selected={seleccion.profesores}
                onChange={(profs) => onChange({ ...seleccion, profesores: profs })}
                catedraLabel={catedraSeleccionada?.titular ?? null}
                disabled={!isPaid}
                onLockedClick={() => openPaywall("profesores")}
              />
            )}
          </div>
          <div>
            <p className="mb-1 text-xs font-medium text-muted-foreground">
              Sede
            </p>
            {subLoading ? (
              <Skeleton className="h-9 w-full rounded-lg" />
            ) : (
              <SedeDropdown
                sedes={sedesUniverse}
                disponibles={sedesDisponibles}
                selected={seleccion.sede ?? null}
                onSelect={(sede) => onChange({ ...seleccion, sede })}
                disabled={!isPaid}
                onLockedClick={() => openPaywall("filtros")}
              />
            )}
          </div>
        </div>
      )}
    </div>
  );
}

// Línea de metadatos de una opción de cátedra: estrellas de reseñas (si tiene) +
// cantidad de profesores. Las estrellas ayudan a decidir cátedra al armar el plan.
function CatedraOptionMeta({ c }: { c: CatedraOpcion }) {
  return (
    <span className="flex flex-wrap items-center gap-x-1.5 gap-y-0.5 text-xs text-muted-foreground">
      {c.review_count > 0 ? (
        <span className="flex items-center gap-1">
          <StarRating value={c.avg_rating ?? 0} size={12} />
          <span className="font-medium text-foreground">
            {c.avg_rating?.toFixed(1)}
          </span>
          <span>({c.review_count})</span>
        </span>
      ) : (
        <span>Sin reseñas</span>
      )}
      <span aria-hidden className="text-muted-foreground/40">
        ·
      </span>
      <span>{c.profesores.length} prof. en comisiones</span>
    </span>
  );
}

function CatedraDropdown({
  catedras,
  disponibles,
  selected,
  onSelect,
  disabled,
  onLockedClick,
}: {
  catedras: CatedraOpcion[];
  disponibles: Set<number>;
  selected: number | null;
  onSelect: (id: number | null) => void;
  disabled?: boolean;
  onLockedClick?: () => void;
}) {
  const [open, setOpen] = useState(false);
  const isWide = useIsWide();
  const sel = catedras.find((c) => c.id === selected);
  const habilitadas = catedras.filter((c) => disponibles.has(c.id));
  const noDisponibles = catedras.filter((c) => !disponibles.has(c.id));
  const label = sel
    ? `Cát ${sel.numero ?? sel.id}${sel.titular ? ` · ${sel.titular}` : ""}`
    : `Todas (${catedras.length})`;

  if (disabled) {
    return (
      <button
        type="button"
        onClick={onLockedClick}
        title="Hacete Pro para elegir una cátedra específica"
        className="flex h-9 w-full items-center gap-2 rounded-lg border border-input bg-muted/40 px-3 text-left text-xs font-medium text-muted-foreground transition-colors hover:bg-muted max-sm:min-h-[44px]"
      >
        <GraduationCap className="size-3.5 shrink-0" />
        <span className="flex-1 truncate">{label}</span>
        <Gem className="size-3.5 shrink-0 text-[#EC990B]" />
      </button>
    );
  }

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button
          type="button"
          className="flex h-9 w-full items-center gap-2 rounded-lg border border-input bg-white px-3 text-left text-xs font-medium transition-colors hover:bg-accent max-sm:min-h-[44px]"
        >
          <GraduationCap className="size-3.5 shrink-0 text-muted-foreground" />
          <span className="flex-1 truncate">{label}</span>
          <ChevronDown className="size-3.5 shrink-0 text-muted-foreground" />
        </button>
      </PopoverTrigger>
      <PopoverContent
        className="w-[min(20rem,calc(100vw-2rem))] p-1"
        align={isWide ? "start" : "center"}
      >
        <button
          type="button"
          onClick={() => {
            onSelect(null);
            setOpen(false);
          }}
          className={
            "flex w-full items-center gap-2 rounded-md px-2 py-2 text-left text-sm transition-colors hover:bg-accent max-sm:min-h-[44px] " +
            (selected === null ? "bg-accent font-medium" : "")
          }
        >
          <span>Todas las cátedras</span>
          <span className="ml-auto text-xs text-muted-foreground">
            {catedras.length}
          </span>
        </button>
        <Separator className="my-1" />
        {habilitadas.map((c) => (
          <button
            key={c.id}
            type="button"
            onClick={() => {
              onSelect(c.id);
              setOpen(false);
            }}
            className={
              "flex w-full flex-col items-start gap-0.5 rounded-md px-2 py-2 text-left text-sm transition-colors hover:bg-accent max-sm:min-h-[44px] " +
              (selected === c.id ? "bg-accent" : "")
            }
          >
            <span className="font-medium">
              Cát {c.numero ?? c.id}
              {c.titular ? <> · <span className="font-normal">{c.titular}</span></> : null}
            </span>
            <CatedraOptionMeta c={c} />
          </button>
        ))}
        {noDisponibles.length > 0 && (
          <>
            <Separator className="my-1" />
            <p className="px-2 py-1 text-xs text-muted-foreground">
              No disponibles para la selección actual
            </p>
            {noDisponibles.map((c) => (
              <button
                key={c.id}
                type="button"
                disabled
                className="flex w-full cursor-not-allowed flex-col items-start gap-0.5 rounded-md px-2 py-2 text-left text-sm opacity-50"
              >
                <span className="font-medium">
                  Cát {c.numero ?? c.id}
                  {c.titular ? <> · <span className="font-normal">{c.titular}</span></> : null}
                </span>
                <CatedraOptionMeta c={c} />
              </button>
            ))}
          </>
        )}
      </PopoverContent>
    </Popover>
  );
}

// Estrella única + promedio para un profesor (sólo si tiene reseñas).
function ProfesorRatingBadge({ rating }: { rating?: ProfesorRating }) {
  if (!rating || rating.review_count === 0 || rating.avg_rating === null) {
    return null;
  }
  return (
    <span className="flex shrink-0 items-center gap-0.5 text-xs text-muted-foreground">
      <Star className="size-3 fill-amber-400 text-amber-400" strokeWidth={1.5} />
      <span className="font-medium text-foreground">
        {rating.avg_rating.toFixed(1)}
      </span>
    </span>
  );
}

function ProfesoresDropdown({
  profesores,
  disponibles,
  ratings,
  selected,
  onChange,
  catedraLabel,
  disabled,
  onLockedClick,
}: {
  profesores: string[];
  disponibles: string[];
  ratings: Record<string, ProfesorRating>;
  selected: string[] | null;
  onChange: (profs: string[] | null) => void;
  catedraLabel: string | null;
  disabled?: boolean;
  onLockedClick?: () => void;
}) {
  const [open, setOpen] = useState(false);
  const isWide = useIsWide();
  const disponiblesSet = new Set(disponibles);
  const noDisponibles = profesores.filter((p) => !disponiblesSet.has(p));

  // Estados (sobre los profesores disponibles, que son los seleccionables):
  //   selected === null            -> todos (sentinel)
  //   selected.length === 0        -> ninguno explícito
  //   selected cubre los disponibles -> todos materializado
  //   subset                       -> selección parcial
  const allSelected =
    selected === null ||
    (selected.length === disponibles.length && disponibles.length > 0);
  const noneSelected = selected !== null && selected.length === 0;

  const label = allSelected
    ? `Todos (${disponibles.length})`
    : noneSelected
    ? "Ninguno"
    : `${selected!.length} de ${disponibles.length}`;

  if (disabled) {
    return (
      <button
        type="button"
        onClick={onLockedClick}
        title="Hacete Pro para filtrar profesores"
        className="flex h-9 w-full items-center gap-2 rounded-lg border border-input bg-muted/40 px-3 text-left text-xs font-medium text-muted-foreground transition-colors hover:bg-muted max-sm:min-h-[44px]"
      >
        <Users className="size-3.5 shrink-0" />
        <span className="flex-1 truncate">{label}</span>
        <Gem className="size-3.5 shrink-0 text-[#EC990B]" />
      </button>
    );
  }

  function toggle(prof: string) {
    if (selected === null) {
      // Estaban todos implícitamente; pasamos a modo explícito sin éste.
      onChange(disponibles.filter((p) => p !== prof));
      return;
    }
    if (selected.includes(prof)) {
      onChange(selected.filter((p) => p !== prof));
    } else {
      onChange([...selected, prof]);
    }
  }

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button
          type="button"
          className="flex h-9 w-full items-center gap-2 rounded-lg border border-input bg-white px-3 text-left text-xs font-medium transition-colors hover:bg-accent max-sm:min-h-[44px]"
        >
          <Users className="size-3.5 shrink-0 text-muted-foreground" />
          <span className="flex-1 truncate">{label}</span>
          <ChevronDown className="size-3.5 shrink-0 text-muted-foreground" />
        </button>
      </PopoverTrigger>
      <PopoverContent
        className="w-[min(20rem,calc(100vw-2rem))] p-2"
        align={isWide ? "start" : "center"}
      >
        <p className="px-2 pb-2 text-xs text-muted-foreground">
          {catedraLabel
            ? `Profesores de ${catedraLabel}.`
            : "Profesores de todas las cátedras."}
        </p>
        <div className="flex items-center justify-end gap-2 px-1 pb-2">
          <button
            type="button"
            onClick={() =>
              allSelected ? onChange([]) : onChange(null)
            }
            disabled={disponibles.length === 0}
            className="text-xs text-primary disabled:cursor-not-allowed disabled:text-muted-foreground"
          >
            {allSelected ? "Deseleccionar todos" : "Seleccionar todos"}
          </button>
        </div>
        <div className="max-h-72 overflow-y-auto pr-1">
          {disponibles.length === 0 && noDisponibles.length === 0 ? (
            <p className="py-4 text-center text-xs text-muted-foreground">
              No hay profesores disponibles.
            </p>
          ) : (
            <>
              {disponibles.map((p) => {
                const isSelected =
                  selected === null ? true : selected.includes(p);
                return (
                  <label
                    key={p}
                    className="flex cursor-pointer items-center gap-2 rounded-md px-2 py-1.5 text-sm transition-colors hover:bg-accent max-sm:min-h-[44px]"
                  >
                    <Checkbox
                      checked={isSelected}
                      onCheckedChange={() => toggle(p)}
                    />
                    <span className="flex-1 truncate">{p}</span>
                    <ProfesorRatingBadge rating={ratings[p]} />
                  </label>
                );
              })}
              {noDisponibles.length > 0 && (
                <>
                  <Separator className="my-1" />
                  <p className="px-2 py-1 text-xs text-muted-foreground">
                    No disponibles para la selección actual
                  </p>
                  {noDisponibles.map((p) => (
                    <label
                      key={p}
                      className="flex items-center gap-2 rounded-md px-2 py-1.5 text-sm opacity-50"
                    >
                      <Checkbox checked={false} disabled />
                      <span className="flex-1 truncate">{p}</span>
                      <ProfesorRatingBadge rating={ratings[p]} />
                    </label>
                  ))}
                </>
              )}
            </>
          )}
        </div>
      </PopoverContent>
    </Popover>
  );
}

function SedeDropdown({
  sedes,
  disponibles,
  selected,
  onSelect,
  disabled,
  onLockedClick,
}: {
  sedes: Array<{ codigo: string; nombre: string }>;
  disponibles: Set<string>;
  selected: string | null;
  onSelect: (sede: string | null) => void;
  disabled?: boolean;
  onLockedClick?: () => void;
}) {
  const [open, setOpen] = useState(false);
  const isWide = useIsWide();
  const habilitadas = sedes.filter((s) => disponibles.has(s.codigo));
  const noDisponibles = sedes.filter((s) => !disponibles.has(s.codigo));
  // Para el label usamos SEDES (lookup completo) por si la selección quedó
  // en una sede que ya no aparece entre las de la materia.
  const sel = SEDES.find((s) => s.codigo === selected);
  const label = sel ? `${sel.nombre} (${sel.codigo})` : "Cualquiera";

  if (disabled) {
    return (
      <button
        type="button"
        onClick={onLockedClick}
        title="Hacete Pro para forzar una sede"
        className="flex h-9 w-full items-center gap-2 rounded-lg border border-input bg-muted/40 px-3 text-left text-xs font-medium text-muted-foreground transition-colors hover:bg-muted max-sm:min-h-[44px]"
      >
        <MapPin className="size-3.5 shrink-0" />
        <span className="flex-1 truncate">{label}</span>
        <Gem className="size-3.5 shrink-0 text-[#EC990B]" />
      </button>
    );
  }

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button
          type="button"
          className="flex h-9 w-full items-center gap-2 rounded-lg border border-input bg-white px-3 text-left text-xs font-medium transition-colors hover:bg-accent max-sm:min-h-[44px]"
        >
          <MapPin className="size-3.5 shrink-0 text-muted-foreground" />
          <span className="flex-1 truncate">{label}</span>
          <ChevronDown className="size-3.5 shrink-0 text-muted-foreground" />
        </button>
      </PopoverTrigger>
      <PopoverContent
        className="w-[min(20rem,calc(100vw-2rem))] p-1"
        align={isWide ? "start" : "center"}
      >
        <button
          type="button"
          onClick={() => {
            onSelect(null);
            setOpen(false);
          }}
          className={
            "flex w-full items-center gap-2 rounded-md px-2 py-2 text-left text-sm transition-colors hover:bg-accent max-sm:min-h-[44px] " +
            (selected === null ? "bg-accent font-medium" : "")
          }
        >
          <span>Cualquier sede</span>
        </button>
        <Separator className="my-1" />
        {habilitadas.map((s) => (
          <button
            key={s.codigo}
            type="button"
            onClick={() => {
              onSelect(s.codigo);
              setOpen(false);
            }}
            className={
              "flex w-full items-center justify-between gap-2 rounded-md px-2 py-2 text-left text-sm transition-colors hover:bg-accent max-sm:min-h-[44px] " +
              (selected === s.codigo ? "bg-accent font-medium" : "")
            }
          >
            <span>{s.nombre}</span>
            <span className="text-xs text-muted-foreground">{s.codigo}</span>
          </button>
        ))}
        {noDisponibles.length > 0 && (
          <>
            <Separator className="my-1" />
            <p className="px-2 py-1 text-xs text-muted-foreground">
              No disponibles para la selección actual
            </p>
            {noDisponibles.map((s) => (
              <div
                key={s.codigo}
                className="flex w-full items-center justify-between gap-2 rounded-md px-2 py-2 text-sm opacity-50"
              >
                <span>{s.nombre}</span>
                <span className="text-xs text-muted-foreground">{s.codigo}</span>
              </div>
            ))}
          </>
        )}
      </PopoverContent>
    </Popover>
  );
}
