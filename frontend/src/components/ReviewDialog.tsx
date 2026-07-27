import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Check, ChevronDown, Loader2, LogIn, Pencil, Star, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Drawer,
  DrawerClose,
  DrawerContent,
  DrawerTrigger,
} from "@/components/ui/drawer";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { StarRating } from "@/components/StarRating";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";
import { useAuth } from "@/lib/useAuth";
import { useAlert } from "@/lib/alert";
import { useCareer } from "@/lib/career";
import type { CatedraOpcion } from "@/lib/types";

const RATING_LABEL: Record<number, string> = {
  1: "Muy mala",
  2: "Mala",
  3: "Regular",
  4: "Buena",
  5: "Excelente",
};

// Centinela para "no puntuar un profesor" (el Select de shadcn no admite value vacío).
const PROFESOR_NINGUNO = "__ninguno__";

const CURRENT_YEAR = new Date().getFullYear();
// Años de cursada seleccionables: el actual hacia atrás (cubre cursadas viejas).
const YEARS = Array.from({ length: 16 }, (_, i) => CURRENT_YEAR - i);

// Mismo criterio que el buscador de materias del planner: substring sobre texto
// normalizado (sin tildes, minúsculas), con fallback a todas las palabras.
function normalizar(s: string): string {
  return s.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
}

function filtrarMateria(value: string, search: string): number {
  if (!search) return 1;
  const v = normalizar(value);
  const s = normalizar(search.trim());
  if (!s) return 1;
  if (v.startsWith(s)) return 1;
  if (v.includes(s)) return 0.8;
  const palabras = s.split(/\s+/).filter(Boolean);
  if (palabras.length > 1 && palabras.every((p) => v.includes(p))) return 0.5;
  return 0;
}

function catedraLabel(c: CatedraOpcion): string {
  const base = `Cátedra ${c.numero ?? c.id}`;
  return c.titular ? `${base} · ${c.titular}` : base;
}

interface Props {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  // Cuando viene, saltea la selección de materia/cátedra (página de una cátedra).
  // `profesores` son los profesores elegibles de esa cátedra.
  fixedCatedra?: { id: number; label: string; profesores: string[] } | null;
  // Para editar una reseña existente.
  initial?: {
    rating: number;
    comment: string;
    profesor: string | null;
    profesor_rating: number | null;
    anio: number;
  } | null;
  onSaved?: () => void;
}

export function ReviewDialog({
  open,
  onOpenChange,
  fixedCatedra = null,
  initial = null,
  onSaved,
}: Props) {
  const { isAuthenticated, getAccessTokenSilently, openLogin } = useAuth();
  const { carrera } = useCareer();
  const showAlert = useAlert();

  // Anclamos el popover del buscador de materias dentro del DialogContent: si
  // se portalea a <body> queda fuera del scroll-lock del Dialog y no scrollea.
  // Callback ref → state para que el container llegue ya resuelto al popover.
  const [contentEl, setContentEl] = useState<HTMLDivElement | null>(null);

  // Radix portalea Select/Popover a <body>. En touch el DismissableLayer difiere
  // el "pointer down outside" al click siguiente, y ese click lo consume también
  // el layer del Dialog, que se cierra de rebote. Sellamos el cierre de cada
  // overlay interno para descartar el interact-outside inmediato del Dialog.
  const innerLayerClosedAtRef = useRef(0);
  const sealInnerLayerClose = () => {
    innerLayerClosedAtRef.current = Date.now();
  };

  const [materiaCodigo, setMateriaCodigo] = useState<number | null>(null);
  const [catedraId, setCatedraId] = useState<number | null>(null);
  const [profesor, setProfesor] = useState<string | null>(null);
  const [profesorRating, setProfesorRating] = useState(0);
  const [anio, setAnio] = useState<number>(CURRENT_YEAR);
  const [rating, setRating] = useState(0);
  const [comment, setComment] = useState("");
  const [saving, setSaving] = useState(false);
  // Sin cátedra fija el modal tiene 2 pasos: (1) elegir materia + cátedra,
  // (2) puntuar. Con cátedra fija arrancamos directo en el paso 2.
  const [step, setStep] = useState<1 | 2>(1);

  // Reset al abrir. En modo cátedra fija arrancamos ya "resuelto".
  useEffect(() => {
    if (!open) return;
    setMateriaCodigo(null);
    setCatedraId(fixedCatedra ? fixedCatedra.id : null);
    setProfesor(initial?.profesor ?? null);
    setProfesorRating(initial?.profesor_rating ?? 0);
    setAnio(initial?.anio ?? CURRENT_YEAR);
    setRating(initial?.rating ?? 0);
    setComment(initial?.comment ?? "");
    setStep(fixedCatedra ? 2 : 1);
  }, [open, fixedCatedra, initial]);

  const needsPicker = !fixedCatedra;

  const { data: materias, isLoading: materiasLoading } = useQuery({
    queryKey: ["materias-review", carrera],
    queryFn: () => api.listMateriasCached(carrera as string),
    enabled: open && needsPicker && isAuthenticated && !!carrera,
    staleTime: 60 * 60 * 1000,
  });

  const { data: opciones, isLoading: opcionesLoading } = useQuery({
    queryKey: ["materia-opciones", materiaCodigo],
    queryFn: () => api.getMateriaOpciones(materiaCodigo as number),
    enabled: open && needsPicker && materiaCodigo != null,
  });

  const materiaNombre = useMemo(
    () => materias?.find((m) => m.codigo === materiaCodigo)?.nombre ?? null,
    [materias, materiaCodigo],
  );

  const catedraSeleccionadaLabel = useMemo(() => {
    if (catedraId == null) return null;
    const c = opciones?.catedras.find((c) => c.id === catedraId);
    return c ? catedraLabel(c) : null;
  }, [opciones, catedraId]);

  // Profesores elegibles: en modo fijo vienen por prop; en picker salen de la
  // cátedra seleccionada dentro de las opciones de la materia.
  const profesoresDisponibles = useMemo<string[]>(() => {
    if (fixedCatedra) return fixedCatedra.profesores;
    if (catedraId == null) return [];
    return opciones?.catedras.find((c) => c.id === catedraId)?.profesores ?? [];
  }, [fixedCatedra, catedraId, opciones]);

  // La cátedra es obligatoria; el profesor es opcional pero si se eligió hay que
  // puntuarlo.
  const canSave =
    rating >= 1 &&
    catedraId != null &&
    (profesor == null || profesorRating >= 1) &&
    !saving;

  async function guardar() {
    if (catedraId == null || rating < 1) return;
    if (profesor != null && profesorRating < 1) return;
    setSaving(true);
    try {
      const token = await getAccessTokenSilently();
      await api.saveCatedraReview(
        catedraId,
        {
          rating,
          comment: comment.trim() || null,
          profesor,
          profesor_rating: profesor != null ? profesorRating : null,
          anio,
        },
        token,
      );
      onOpenChange(false);
      onSaved?.();
      showAlert({
        variant: "info",
        title: "¡Gracias!",
        message: "Tu reseña se guardó.",
      });
    } catch (e) {
      showAlert({
        variant: "error",
        title: "No se pudo guardar",
        message: (e as Error).message,
      });
    } finally {
      setSaving(false);
    }
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(v) => {
        if (!saving) onOpenChange(v);
      }}
    >
      <DialogContent
        ref={setContentEl}
        onInteractOutside={(e) => {
          if (Date.now() - innerLayerClosedAtRef.current < 400) {
            e.preventDefault();
          }
        }}
        className={cn(
          "flex max-h-[calc(100dvh-2rem)] flex-col",
          needsPicker && "sm:max-w-lg",
        )}
      >
        {!isAuthenticated ? (
          <>
            <DialogHeader>
              <DialogTitle>Iniciá sesión</DialogTitle>
              <DialogDescription>
                Necesitás iniciar sesión para dejar una reseña.
              </DialogDescription>
            </DialogHeader>
            <div className="flex flex-col-reverse gap-2 pt-2 sm:flex-row sm:justify-end">
              <Button variant="outline" onClick={() => onOpenChange(false)}>
                Cancelar
              </Button>
              <Button
                onClick={() => {
                  onOpenChange(false);
                  openLogin("signin");
                }}
              >
                <LogIn className="size-4" />
                Iniciar sesión
              </Button>
            </div>
          </>
        ) : (
          <>
            <DialogHeader className="shrink-0">
              <DialogTitle>
                {initial ? "Editar tu reseña" : "Dejar una reseña"}
              </DialogTitle>
              <DialogDescription>
                {needsPicker && step === 1
                  ? "Elegí la materia y la cátedra"
                  : "Tu reseña es anónima"}
              </DialogDescription>
            </DialogHeader>

            {needsPicker && step === 1 ? (
              <>
                <div className="min-w-0 flex-1 space-y-4 overflow-y-auto py-1 min-h-0">
                  <div className="min-w-0 space-y-1.5">
                    <label className="text-xs font-medium text-muted-foreground">
                      Materia
                    </label>
                    <MateriaPicker
                      materias={materias ?? []}
                      loading={materiasLoading}
                      selected={materiaCodigo}
                      selectedNombre={materiaNombre}
                      popoverContainer={contentEl}
                      onOverlayClose={sealInnerLayerClose}
                      onSelect={(codigo) => {
                        setMateriaCodigo(codigo);
                        setCatedraId(null);
                        setProfesor(null);
                        setProfesorRating(0);
                      }}
                    />
                  </div>

                  <div className="min-w-0 space-y-1.5">
                    <label className="text-xs font-medium text-muted-foreground">
                      Cátedra
                    </label>
                    <Select
                      value={catedraId != null ? String(catedraId) : undefined}
                      onOpenChange={(v) => !v && sealInnerLayerClose()}
                      onValueChange={(v) => {
                        setCatedraId(Number(v));
                        setProfesor(null);
                        setProfesorRating(0);
                      }}
                      disabled={materiaCodigo == null || opcionesLoading}
                    >
                      <SelectTrigger className="[&>span]:min-w-0">
                        <SelectValue
                          placeholder={
                            materiaCodigo == null
                              ? "Elegí una materia primero"
                              : opcionesLoading
                                ? "Cargando cátedras…"
                                : "Elegí una cátedra"
                          }
                        />
                      </SelectTrigger>
                      <SelectContent>
                        {(opciones?.catedras ?? []).map((c) => (
                          <SelectItem key={c.id} value={String(c.id)}>
                            {catedraLabel(c)}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                </div>

                <div className="flex shrink-0 flex-col-reverse gap-2 sm:flex-row sm:justify-end">
                  <Button
                    onClick={() => setStep(2)}
                    disabled={catedraId == null}
                  >
                    Continuar
                  </Button>
                </div>
              </>
            ) : (
              <>
                <div className="min-w-0 flex-1 space-y-4 overflow-y-auto py-1 min-h-0">
                  {needsPicker && (
                    <button
                      type="button"
                      onClick={() => setStep(1)}
                      className="flex w-full items-center gap-2 rounded-lg border border-border bg-muted/30 p-3 text-left transition-colors hover:bg-muted"
                    >
                      <div className="min-w-0 flex-1">
                        <p className="truncate text-sm font-semibold">
                          {materiaNombre}
                        </p>
                        {catedraSeleccionadaLabel && (
                          <p className="truncate text-xs text-muted-foreground">
                            {catedraSeleccionadaLabel}
                          </p>
                        )}
                      </div>
                      <span className="flex shrink-0 items-center gap-1 text-xs font-medium text-primary">
                        <Pencil className="size-3.5" />
                        Cambiar
                      </span>
                    </button>
                  )}

                  {/* Cátedra: puntuación obligatoria */}
                  <div className="space-y-2 rounded-lg border border-border bg-muted/30 p-4">
                <div className="text-center">
                  <p className="text-sm font-semibold">
                    ¿Qué te pareció la cátedra?
                  </p>
                </div>
                <div className="flex flex-col items-center gap-1.5">
                  <StarRating
                    value={rating}
                    size={34}
                    interactive
                    onChange={setRating}
                    disabled={saving}
                  />
                  <span className="text-xs font-medium text-muted-foreground">
                    {RATING_LABEL[rating] ?? "Tocá para puntuar la cátedra"}
                  </span>
                </div>
              </div>

              {/* Profesor: puntuación opcional y separada de la cátedra */}
              <div className="space-y-3 rounded-lg border border-border p-4">
                <div>
                  <p className="text-sm font-semibold">
                    ¿Queres puntuar un profesor?
                  </p>
                  <p className="text-xs text-muted-foreground">
                    Opcional. Si elegís uno, lo puntuás aparte de la cátedra.
                  </p>
                </div>
                <Select
                  // Radix trata value=undefined como "no controlado" y conserva
                  // su selección interna; remontamos al limpiar para que el
                  // trigger vuelva al placeholder.
                  key={profesor ?? "sin-profesor"}
                  value={profesor ?? undefined}
                  onOpenChange={(v) => !v && sealInnerLayerClose()}
                  onValueChange={(v) => {
                    if (v === PROFESOR_NINGUNO) {
                      setProfesor(null);
                      setProfesorRating(0);
                    } else {
                      setProfesor(v);
                      setProfesorRating(0);
                    }
                  }}
                  disabled={
                    catedraId == null || profesoresDisponibles.length === 0
                  }
                >
                  <SelectTrigger className="[&>span]:min-w-0">
                    <SelectValue
                      placeholder={
                        catedraId == null
                          ? "Elegí una cátedra primero"
                          : profesoresDisponibles.length === 0
                            ? "Sin profesores"
                            : "Elegí un profesor (opcional)"
                      }
                    />
                  </SelectTrigger>
                  <SelectContent>
                    {profesor != null && (
                      <SelectItem value={PROFESOR_NINGUNO}>
                        No puntuar un profesor
                      </SelectItem>
                    )}
                    {profesoresDisponibles.map((p) => (
                      <SelectItem key={p} value={p}>
                        {p}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>

                {profesor != null && (
                  <div className="space-y-1.5 rounded-md bg-primary/5 p-3">
                    <div className="flex flex-col items-center gap-1.5">
                      <StarRating
                        value={profesorRating}
                        size={28}
                        interactive
                        onChange={setProfesorRating}
                        disabled={saving}
                      />
                      <span className="text-xs font-medium text-muted-foreground">
                        {RATING_LABEL[profesorRating] ??
                          "Tocá para puntuar al profesor"}
                      </span>
                    </div>
                  </div>
                )}
              </div>

              {/* Año de cursada */}
              <div className="space-y-1.5">
                <label className="text-xs font-medium text-muted-foreground">
                  Año de cursada
                </label>
                <Select
                  value={String(anio)}
                  onOpenChange={(v) => !v && sealInnerLayerClose()}
                  onValueChange={(v) => setAnio(Number(v))}
                >
                  <SelectTrigger className="sm:w-40">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {YEARS.map((y) => (
                      <SelectItem key={y} value={String(y)}>
                        {y}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              <div>
                <Textarea
                  value={comment}
                  onChange={(e) => setComment(e.target.value.slice(0, 1000))}
                  maxLength={1000}
                  rows={4}
                  placeholder="Comentario (opcional): cursada, parciales, profesores…"
                  disabled={saving}
                />
                <div className="mt-1 text-right text-xs text-muted-foreground">
                  {comment.length}/1000
                </div>
              </div>
            </div>

                <div className="flex shrink-0 flex-col-reverse gap-2 sm:flex-row sm:justify-end">
                  <Button onClick={guardar} disabled={!canSave}>
                    {saving ? (
                      <Loader2 className="size-4 animate-spin" />
                    ) : (
                      <Star className="size-4" />
                    )}
                    {initial ? "Guardar cambios" : "Publicar reseña"}
                  </Button>
                </div>
              </>
            )}
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}

function MateriaPicker({
  materias,
  loading,
  selected,
  selectedNombre,
  popoverContainer,
  onSelect,
  onOverlayClose,
}: {
  materias: { codigo: number; nombre: string }[];
  loading: boolean;
  selected: number | null;
  selectedNombre: string | null;
  popoverContainer?: HTMLElement | null;
  onSelect: (codigo: number) => void;
  onOverlayClose: () => void;
}) {
  const [popoverOpen, setPopoverOpen] = useState(false);
  const [drawerOpen, setDrawerOpen] = useState(false);

  const triggerClass =
    "flex h-10 w-full items-center gap-2 rounded-lg border border-input bg-white px-3 text-left text-sm transition-colors hover:bg-accent max-sm:min-h-[44px]";

  const triggerContent = (
    <>
      <span
        className={cn(
          "min-w-0 flex-1 truncate",
          !selectedNombre && "text-muted-foreground",
        )}
      >
        {selectedNombre ?? "Elegí una materia"}
      </span>
      <ChevronDown className="size-4 shrink-0 text-muted-foreground" />
    </>
  );

  const commandBody = (drawer = false) => (
    <Command
      shouldFilter
      filter={filtrarMateria}
      className={cn(
        "rounded-lg",
        drawer &&
          "rounded-none [&_[cmdk-input-wrapper]]:mb-2 [&_[cmdk-input-wrapper]]:ml-4 [&_[cmdk-input-wrapper]]:mr-[4.25rem] [&_[cmdk-input-wrapper]]:mt-4 [&_[cmdk-input-wrapper]]:h-11 [&_[cmdk-input-wrapper]]:rounded-full [&_[cmdk-input-wrapper]]:border [&_[cmdk-input-wrapper]]:border-input [&_[cmdk-input-wrapper]]:bg-white [&_[cmdk-input-wrapper]]:pr-3",
      )}
    >
      <CommandInput
        placeholder="Buscar materia…"
        className={cn("pr-12 wide:pr-0", drawer && "text-base")}
      />
      <CommandList className={drawer ? "max-h-none flex-1 pb-4" : "max-h-64"}>
        {loading ? (
          <div className="py-6 text-center text-sm text-muted-foreground">
            Cargando materias…
          </div>
        ) : (
          <>
            <CommandEmpty>No se encontraron materias.</CommandEmpty>
            <CommandGroup>
              {materias.map((m) => (
                <CommandItem
                  key={m.codigo}
                  value={`${m.nombre} ${m.codigo}`}
                  onSelect={() => {
                    onSelect(m.codigo);
                    setPopoverOpen(false);
                    setDrawerOpen(false);
                  }}
                >
                  <span className="line-clamp-2 flex-1">{m.nombre}</span>
                  {selected === m.codigo && (
                    <Check className="ml-2 size-4 shrink-0 text-primary" />
                  )}
                </CommandItem>
              ))}
            </CommandGroup>
          </>
        )}
      </CommandList>
    </Command>
  );

  return (
    <>
      {/* Desktop: dropdown con buscador */}
      <Popover
        open={popoverOpen}
        onOpenChange={(v) => {
          setPopoverOpen(v);
          if (!v) onOverlayClose();
        }}
      >
        <PopoverTrigger asChild>
          <button
            type="button"
            className={cn(triggerClass, "hidden wide:flex")}
          >
            {triggerContent}
          </button>
        </PopoverTrigger>
        <PopoverContent
          align="start"
          container={popoverContainer}
          className="hidden p-0 wide:block"
          style={{ width: "var(--radix-popover-trigger-width)" }}
        >
          {commandBody()}
        </PopoverContent>
      </Popover>

      {/* Mobile: bottom sheet (igual que el generador de planes) */}
      <Drawer
        open={drawerOpen}
        onOpenChange={(v) => {
          setDrawerOpen(v);
          if (!v) onOverlayClose();
        }}
        shouldScaleBackground={false}
      >
        <DrawerTrigger asChild>
          <button type="button" className={cn(triggerClass, "wide:hidden")}>
            {triggerContent}
          </button>
        </DrawerTrigger>
        <DrawerContent
          showHandle={false}
          // Sin autofocus: si enfocamos el input, el teclado virtual salta y
          // tapa media pantalla antes de que el usuario decida si va a buscar.
          onOpenAutoFocus={(e) => e.preventDefault()}
          className="h-[calc(100dvh-16px)] max-h-[calc(100dvh-16px)] overflow-hidden rounded-t-2xl border-0"
        >
          <div className="relative flex min-h-0 flex-1 flex-col">
            {commandBody(true)}
            <DrawerClose asChild>
              <Button
                type="button"
                variant="ghost"
                size="icon"
                aria-label="Cerrar"
                className="absolute right-4 top-4 size-11 rounded-full border border-input bg-white"
              >
                <X className="size-4" />
              </Button>
            </DrawerClose>
          </div>
        </DrawerContent>
      </Drawer>
    </>
  );
}
