from __future__ import annotations

from collections import deque
from dataclasses import dataclass

VACIO = "(sin mensajes previos)"


@dataclass(frozen=True)
class Mensaje:
    rol: str  # "usuario" | "asistente"
    texto: str


class MemoriaVentana:
    """Historial acotado a los ultimos `ventana` mensajes (usuario y asistente cuentan aparte).

    Reemplaza a las memorias clasicas de LangChain (ahora en `langchain-classic`): el estado vive
    en la propia conversacion y no depende de una cadena concreta.
    """

    def __init__(self, ventana: int = 6):
        if ventana < 1:
            raise ValueError("la ventana debe ser al menos 1")
        self.ventana = ventana
        self._mensajes: deque[Mensaje] = deque(maxlen=ventana)

    def agregar(self, rol: str, texto: str) -> None:
        if rol not in ("usuario", "asistente"):
            raise ValueError(f"rol desconocido: {rol!r}")
        self._mensajes.append(Mensaje(rol, texto))

    @property
    def mensajes(self) -> list[Mensaje]:
        return list(self._mensajes)

    def ultimo_del_usuario(self) -> str | None:
        return next((m.texto for m in reversed(self._mensajes) if m.rol == "usuario"), None)

    def limpiar(self) -> None:
        self._mensajes.clear()

    def formatear(self) -> str:
        if not self._mensajes:
            return VACIO
        etiquetas = {"usuario": "Usuario", "asistente": "Asistente"}
        return "\n".join(f"{etiquetas[m.rol]}: {m.texto}" for m in self._mensajes)
