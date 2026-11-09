class ErrorIngesta(Exception):
    """Base de los errores de la ingesta desde GitHub."""


class ErrorRepositorioInvalido(ErrorIngesta, ValueError):
    """El identificador no tiene la forma propietario/repositorio."""


class ErrorNoEncontrado(ErrorIngesta):
    """El repositorio no existe o no es publico."""


class ErrorRepositorioVacio(ErrorIngesta):
    """GitHub responde 409: el repositorio no tiene commits."""


class ErrorAutenticacion(ErrorIngesta):
    """Token rechazado (401)."""


class ErrorAccesoDenegado(ErrorIngesta):
    """Acceso prohibido que no corresponde al limite de tasa (403)."""


class ErrorLimiteTasa(ErrorIngesta):
    """Limite de tasa agotado y la espera supera el maximo permitido."""

    def __init__(self, espera: float):
        super().__init__(f"limite de tasa agotado; el cupo se repone en {espera:.0f} s")
        self.espera = espera


class ErrorRed(ErrorIngesta):
    """Sin conexion o tiempo de espera agotado tras los reintentos."""


class ErrorServidor(ErrorIngesta):
    """Error 5xx persistente de GitHub."""
