import { useEffect, useState } from "react";
import { Heart, Loader2, Pencil } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";

// Mismos límites que el backend (FavoriteMeta en api/favoritos.py).
export const NOMBRE_MAX = 80;
export const DESCRIPCION_MAX = 300;

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  mode: "guardar" | "editar";
  initialNombre?: string | null;
  initialDescripcion?: string | null;
  saving: boolean;
  onSubmit: (nombre: string, descripcion: string | null) => void;
}

export function FavoritoFormDialog({
  open,
  onOpenChange,
  mode,
  initialNombre,
  initialDescripcion,
  saving,
  onSubmit,
}: Props) {
  const editando = mode === "editar";
  const [nombre, setNombre] = useState("");
  const [descripcion, setDescripcion] = useState("");

  // Se resetea al abrir, no al montar: el dialog vive montado en el padre y se
  // reusa para distintos favoritos. Las deps son los valores y no un objeto
  // `initial` — si no, cada render del padre pisaría lo que el usuario tipeó.
  useEffect(() => {
    if (!open) return;
    setNombre(initialNombre ?? "");
    setDescripcion(initialDescripcion ?? "");
  }, [open, initialNombre, initialDescripcion]);

  const puedeGuardar = nombre.trim().length > 0 && !saving;

  function submit() {
    if (!puedeGuardar) return;
    onSubmit(nombre.trim(), descripcion.trim() || null);
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(v) => {
        if (!v && saving) return;
        onOpenChange(v);
      }}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>
            {editando ? "Editar plan" : "Guardar este plan"}
          </DialogTitle>
          <DialogDescription>
            {editando
              ? "Cambiá el nombre o la descripción de este plan guardado."
              : "Ponele un nombre para reconocerlo después entre tus planes guardados."}
          </DialogDescription>
        </DialogHeader>

        <form
          className="space-y-4"
          onSubmit={(e) => {
            e.preventDefault();
            submit();
          }}
        >
          <div className="space-y-2">
            <Label htmlFor="favorito-nombre">Nombre</Label>
            <Input
              id="favorito-nombre"
              value={nombre}
              onChange={(e) => setNombre(e.target.value.slice(0, NOMBRE_MAX))}
              maxLength={NOMBRE_MAX}
              placeholder="Ej: Plan A"
              disabled={saving}
              autoFocus
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="favorito-descripcion">
              Descripción{" "}
              <span className="font-normal text-muted-foreground">
                (opcional)
              </span>
            </Label>
            <Textarea
              id="favorito-descripcion"
              value={descripcion}
              onChange={(e) =>
                setDescripcion(e.target.value.slice(0, DESCRIPCION_MAX))
              }
              maxLength={DESCRIPCION_MAX}
              rows={3}
              placeholder="Ej: el que me deja los viernes libres"
              disabled={saving}
            />
            <div className="text-right text-xs text-muted-foreground">
              {descripcion.length}/{DESCRIPCION_MAX}
            </div>
          </div>

          <div className="flex flex-col gap-2 sm:flex-row sm:justify-end">
            <Button type="submit" disabled={!puedeGuardar}>
              {saving ? (
                <Loader2 className="size-4 animate-spin" />
              ) : editando ? (
                <Pencil className="size-4" />
              ) : (
                <Heart className="size-4" />
              )}
              {editando ? "Guardar cambios" : "Guardar"}
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}
