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
      "Sin " + f.dias_excluidos.map((d) => DIA_LABELS[d] ?? d).join("/")
    );
  }
  for (const fr of f.franjas_excluidas) {
    const dias = fr.dias.map((d) => DIA_LABELS[d] ?? d).join("/");
    out.push(`${dias} ${fr.hora_inicio}-${fr.hora_fin} bloqueada`);
  }
  if (f.sedes_permitidas.length > 0) {
    const labels = f.sedes_permitidas.map(
      (s) => SEDES.find((x) => x.codigo === s)?.nombre ?? s
    );
    out.push("Sede: " + labels.join(", "));
  }
  if (f.max_bache_horas != null) {
    out.push(`Bache ≤ ${f.max_bache_horas}h`);
  }
  for (const m of f.materias) {
    const partes: string[] = [];
    if (m.catedra_id !== null) partes.push("cátedra fija");
    if (m.profesores && m.profesores.length > 0) {
      partes.push(`${m.profesores.length} prof.`);
    }
    if (m.sede) {
      const sede = SEDES.find((x) => x.codigo === m.sede)?.nombre ?? m.sede;
      partes.push(`sede ${sede}`);
    }
    if (partes.length > 0) {
      out.push(`${m.nombre}: ${partes.join(", ")}`);
    }
  }
  return out;
}

function FavoritoCard({
  fav,
  onDelete,
  deleting,
}: {
  fav: Favorite;
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
              "size-5 shrink-0 text-muted-foreground transition-transform " +
              (expanded ? "rotate-180" : "")
            }
          />
          <div className="min-w-0 flex-1">
            <p className="mb-2 text-xs text-muted-foreground">
              Guardado el {formatFecha(fav.created_at)}
            </p>
            <PlanLeyenda plan={fav.plan} />
            {chips.length > 0 && (
              <div className="mt-2 flex flex-wrap gap-1.5">
                {chips.map((c) => (
                  <span
                    key={c}
                    className="rounded-full bg-muted px-2 py-0.5 text-[11px] font-medium text-muted-foreground"
                  >
                    {c}
                  </span>
                ))}
              </div>
            )}
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
              onClick={() => onDelete(fav.id)}
              disabled={deleting}
              className="w-full justify-start text-muted-foreground hover:text-destructive"
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
        <CardContent>
          <CalendarioPlan
            plan={fav.plan}
            showLeyenda={false}
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

  const { data, isLoading, error, refetch, isFetching } = useQuery({
    queryKey: ["favoritos"],
    queryFn: async () => {
      const token = await getAccessTokenSilently();
      return api.listFavoritos(token);
    },
    enabled: isAuthenticated,
  });

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
              Lo vas a quitar de tus favoritos. Esta acción no se puede deshacer.
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
    </div>
  );
}
