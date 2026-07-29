import { useState } from "react";
import { useAuth } from "@/lib/useAuth";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ChevronDown,
  Gem,
  Heart,
  Loader2,
  LogIn,
  MoreVertical,
  Pencil,
  Trash2,
} from "lucide-react";
import { usePaywall } from "@/lib/paywall";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Skeleton } from "@/components/ui/skeleton";
import { CalendarioPlan, PlanLeyenda } from "@/components/CalendarioPlan";
import { ErrorState } from "@/components/ErrorState";
import { FavoritoFormDialog } from "@/components/FavoritoFormDialog";
import { Header } from "@/components/Header";
import { Seo } from "@/components/Seo";
import { api } from "@/lib/api";
import { useSubscription } from "@/lib/useSubscription";
import { useAlert } from "@/lib/alert";
import { SEDES, type Favorite } from "@/lib/types";

const DIA_LABELS: Record<string, string> = {
  lunes: "Lun",
  martes: "Mar",
  miercoles: "Mié",
  jueves: "Jue",
  viernes: "Vie",
  sabado: "Sáb",
};

function formatFecha(iso: string) {
  return new Date(iso).toLocaleDateString("es-AR", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
  });
}

function filtrosChips(fav: Favorite): string[] {
  const f = fav.filters;
  if (!f) return [];
  const out: string[] = [];
  if (f.dias_excluidos.length > 0) {
    out.push(
      "Sin " + f.dias_excluidos.map((d) => DIA_LABELS[d] ?? d).join("/"),
    );
  }
  for (const fr of f.franjas_excluidas) {
    const dias = fr.dias.map((d) => DIA_LABELS[d] ?? d).join("/");
    out.push(`${dias} ${fr.hora_inicio}-${fr.hora_fin} bloqueada`);
  }
  if (f.sedes_permitidas.length > 0) {
    const labels = f.sedes_permitidas.map(
      (s) => SEDES.find((x) => x.codigo === s)?.nombre ?? s,
    );
    out.push("Sede: " + labels.join(", "));
  }
  if (f.max_bache_horas != null) {
    out.push(`Bache ≤ ${f.max_bache_horas}h`);
  }
  const dias = rango(f.min_dias_semana, f.max_dias_semana);
  if (dias) out.push(`${dias} días por semana`);
  const horas = rango(f.min_horas_dia, f.max_horas_dia);
  if (horas) out.push(`${horas} horas por día`);
  if (f.solo_con_cupos) out.push("Solo con cupos");
  for (const m of f.materias) {
    const partes: string[] = [];
    if (m.catedra_id !== null) partes.push("cátedra fija");
    if (m.comision_codigo) partes.push(`comisión ${m.comision_codigo}`);
    if (m.profesores && m.profesores.length > 0) {
      partes.push(`${m.profesores.length} prof.`);
    }
    if (m.sede) {
      const sede = SEDES.find((x) => x.codigo === m.sede)?.nombre ?? m.sede;
      partes.push(`sede ${sede}`);
    }
    if (m.teorico_libre) partes.push("teórico libre");
    if (m.seminario_libre) partes.push("seminario libre");
    if (partes.length > 0) {
      out.push(`${m.nombre}: ${partes.join(", ")}`);
    }
  }
  return out;
}

// "2-4", "≥ 2" o "≤ 4" según qué extremos vinieron en el snapshot.
function rango(min?: number | null, max?: number | null): string | null {
  if (min != null && max != null)
    return min === max ? `${min}` : `${min}-${max}`;
  if (min != null) return `≥ ${min}`;
  if (max != null) return `≤ ${max}`;
  return null;
}

function FavoritoCard({
  fav,
  onEdit,
  onDelete,
  deleting,
}: {
  fav: Favorite;
  onEdit: (fav: Favorite) => void;
  onDelete: (id: number) => void;
  deleting: boolean;
}) {
  const [expanded, setExpanded] = useState(false);
  const chips = filtrosChips(fav);

  return (
    <Card>
      <CardHeader className="flex-row items-start justify-between gap-3">
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          className="flex min-w-0 flex-1 items-start gap-3 text-left"
        >
          <ChevronDown
            className={
              "mt-0.5 size-5 shrink-0 text-muted-foreground transition-transform " +
              (expanded ? "rotate-180" : "")
            }
          />
          <div className="min-w-0 flex-1">
            <p className="text-xs text-muted-foreground">
              Guardado el {formatFecha(fav.created_at)}
            </p>
            <div className="flex flex-col gap-0">
              {fav.nombre ? (
                <p className="line-clamp-2 mt-1 break-words font-medium">
                  {fav.nombre}
                </p>
              ) : (
                <p className="line-clamp-2 mt-1 italic text-muted-foreground">
                  Sin nombre
                </p>
              )}
              {fav.descripcion && (
                <p className="line-clamp-2 break-words text-sm text-muted-foreground">
                  {fav.descripcion}
                </p>
              )}
            </div>

            <div className="mt-2">
              <PlanLeyenda
                plan={fav.plan}
                showCatedra={false}
                size="compacto"
              />
            </div>
          </div>
        </button>
        <Popover>
          <PopoverTrigger asChild>
            <Button
              variant="ghost"
              size="icon"
              className="size-8 shrink-0 text-muted-foreground"
            >
              <MoreVertical className="size-4" />
            </Button>
          </PopoverTrigger>
          <PopoverContent align="end" className="w-auto p-1">
            <Button
              variant="ghost"
              size="sm"
              onClick={() => onEdit(fav)}
              className="w-full justify-start text-muted-foreground"
            >
              <Pencil className="size-4" />
              Editar
            </Button>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => onDelete(fav.id)}
              disabled={deleting}
              className="w-full justify-start text-red-500 hover:text-destructive"
            >
              {deleting ? (
                <Loader2 className="size-4 animate-spin" />
              ) : (
                <Trash2 className="size-4" />
              )}
              Eliminar
            </Button>
          </PopoverContent>
        </Popover>
      </CardHeader>
      {expanded && (
        <CardContent className="space-y-4">
          {chips.length > 0 && (
            <div className="flex flex-wrap gap-1.5">
              {chips.map((c) => (
                <span
                  key={c}
                  className="rounded-md bg-muted px-2 py-0.5 text-[11px] font-medium text-muted-foreground"
                >
                  {c}
                </span>
              ))}
            </div>
          )}
          <CalendarioPlan
            plan={fav.plan}
            showCupos={false}
            franjasBloqueadas={fav.filters?.franjas_excluidas}
          />
        </CardContent>
      )}
    </Card>
  );
}

export function Favoritos() {
  const {
    isAuthenticated,
    isLoading: authLoading,
    getAccessTokenSilently,
    openLogin,
  } = useAuth();
  const openPaywall = usePaywall();
  const { isPaid, isLoading: subLoading } = useSubscription();
  const queryClient = useQueryClient();
  const showAlert = useAlert();
  const [deletingId, setDeletingId] = useState<number | null>(null);
  const [confirmId, setConfirmId] = useState<number | null>(null);
  const [editing, setEditing] = useState<Favorite | null>(null);
  const [savingEdit, setSavingEdit] = useState(false);

  const { data, isLoading, error, refetch, isFetching } = useQuery({
    queryKey: ["favoritos"],
    queryFn: async () => {
      const token = await getAccessTokenSilently();
      return api.listFavoritos(token);
    },
    enabled: isAuthenticated,
  });

  async function guardarEdicion(nombre: string, descripcion: string | null) {
    if (!editing) return;
    setSavingEdit(true);
    try {
      const token = await getAccessTokenSilently();
      await api.updateFavorito(editing.id, nombre, descripcion, token);
      queryClient.invalidateQueries({ queryKey: ["favoritos"] });
      setEditing(null);
    } catch (e) {
      showAlert({
        variant: "error",
        title: "No se pudo guardar",
        message: (e as Error).message,
      });
    } finally {
      setSavingEdit(false);
    }
  }

  async function confirmarEliminar() {
    if (confirmId === null) return;
    const id = confirmId;
    setDeletingId(id);
    try {
      const token = await getAccessTokenSilently();
      await api.deleteFavorito(id, token);
      queryClient.invalidateQueries({ queryKey: ["favoritos"] });
      setConfirmId(null);
      showAlert({
        variant: "info",
        title: "Eliminado",
        message: "El plan se quitó de favoritos.",
      });
    } catch (e) {
      showAlert({
        variant: "error",
        title: "No se pudo eliminar",
        message: (e as Error).message,
      });
    } finally {
      setDeletingId(null);
    }
  }

  return (
    <div className="min-h-screen bg-background">
      <Seo
        title="Planes guardados | Planify"
        description="Tus combinaciones de cursada favoritas guardadas en Planify."
        path="/favoritos"
        noindex
      />
      <Header />

      <main className="container max-w-6xl space-y-6 px-4 pb-8 pt-8 sm:px-6">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">
            Planes guardados
          </h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Tus combinaciones favoritas
          </p>
        </div>

        <div className="space-y-4">
          {(authLoading || subLoading) && (
            <Skeleton className="h-32 w-full rounded-xl" />
          )}

          {!authLoading && !isAuthenticated && (
            <Card>
              <CardContent className="flex flex-col items-center gap-4 py-12 text-center text-sm text-muted-foreground">
                <p>Iniciá sesión para ver tus planes guardados.</p>
                <Button onClick={() => openLogin("signin")}>
                  <LogIn className="size-4" />
                  Iniciar sesión
                </Button>
              </CardContent>
            </Card>
          )}

          {isAuthenticated && isLoading && (
            <div className="flex items-center justify-center py-12 text-sm text-muted-foreground">
              <Loader2 className="mr-2 size-4 animate-spin" />
              Cargando…
            </div>
          )}

          {isAuthenticated && error && (
            <Card>
              <CardContent className="py-6">
                <ErrorState
                  title="No pudimos cargar tus favoritos"
                  description="Revisá tu conexión y volvé a intentar."
                  onRetry={() => refetch()}
                  retrying={isFetching}
                />
              </CardContent>
            </Card>
          )}

          {isAuthenticated &&
            !isLoading &&
            !subLoading &&
            !isPaid &&
            data?.favorites.length === 0 && (
              <Card>
                <CardContent className="flex flex-col items-center gap-4 py-12 text-center text-sm text-muted-foreground">
                  <p>Para empezar a guardar planes tenés que ser Pro.</p>
                  <Button
                    onClick={() => openPaywall("favoritos")}
                    className="bg-[#EC990B] text-white hover:bg-[#EC990B]/90"
                  >
                    <Gem className="size-4" />
                    Hacete Pro
                  </Button>
                </CardContent>
              </Card>
            )}

          {isAuthenticated && isPaid && data && data.favorites.length === 0 && (
            <Card>
              <CardContent className="py-12 text-center text-sm text-muted-foreground">
                <Heart className="mx-auto mb-3 size-8 text-muted-foreground/50" />
                Todavía no guardaste ningún plan. Generá tus planes y tocá el
                corazón para guardar el que más te guste.
              </CardContent>
            </Card>
          )}

          {isAuthenticated && data && data.favorites.length > 0 && !isPaid && (
            <div className="rounded-2xl border border-amber-300 bg-amber-50 p-4 text-sm text-amber-900">
              <p>
                Tu suscripción Pro no está activa. Podés seguir viendo y
                eliminando los planes que guardaste, pero para agregar nuevos
                tenés que ser Pro.
              </p>
            </div>
          )}

          {isAuthenticated &&
            data?.favorites.map((fav) => (
              <FavoritoCard
                key={fav.id}
                fav={fav}
                onEdit={(f) => setEditing(f)}
                onDelete={(id) => setConfirmId(id)}
                deleting={deletingId === fav.id}
              />
            ))}
        </div>
      </main>

      <Dialog
        open={confirmId !== null}
        onOpenChange={(v) => {
          if (!v && deletingId === null) setConfirmId(null);
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>¿Eliminar este plan?</DialogTitle>
            <DialogDescription>
              Lo vas a quitar de tus favoritos. Esta acción no se puede
              deshacer.
            </DialogDescription>
          </DialogHeader>
          <div className="flex justify-end gap-2 pt-2">
            <Button
              variant="outline"
              onClick={() => setConfirmId(null)}
              disabled={deletingId !== null}
            >
              Cancelar
            </Button>
            <Button
              onClick={confirmarEliminar}
              disabled={deletingId !== null}
              className="bg-red-500 text-white hover:bg-red-500/90"
            >
              {deletingId !== null ? (
                <Loader2 className="size-4 animate-spin" />
              ) : (
                <Trash2 className="size-4" />
              )}
              Eliminar
            </Button>
          </div>
        </DialogContent>
      </Dialog>

      <FavoritoFormDialog
        open={editing !== null}
        onOpenChange={(v) => {
          if (!v) setEditing(null);
        }}
        mode="editar"
        initialNombre={editing?.nombre}
        initialDescripcion={editing?.descripcion}
        saving={savingEdit}
        onSubmit={guardarEdicion}
      />
    </div>
  );
}
