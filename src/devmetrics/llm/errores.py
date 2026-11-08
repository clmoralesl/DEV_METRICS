class ErrorLLM(Exception):
    """Error base de la capa de modelos de lenguaje."""


class ErrorConfiguracion(ErrorLLM):
    """Configuracion ausente o invalida (proveedor desconocido, falta la clave)."""


class ErrorSinRed(ErrorLLM):
    """No hay conexion con el proveedor (red caida, Ollama apagado, tiempo agotado)."""


class ErrorClaveInvalida(ErrorLLM):
    """El proveedor rechazo la clave de API."""


class ErrorAccesoDenegado(ErrorLLM):
    """El proveedor nego el acceso (403): proyecto sin cupo gratuito, region o permisos."""


class ErrorCupoAgotado(ErrorLLM):
    """Se agoto el cupo o el limite de solicitudes del proveedor."""


class ErrorProveedor(ErrorLLM):
    """Fallo no clasificado del proveedor."""


class ErrorServidor(ErrorProveedor):
    """Fallo transitorio del servidor (5xx, sobrecarga); reintentable."""


class ErrorTodosFallaron(ErrorLLM):
    """Fallaron el proveedor principal y el de respaldo."""

    def __init__(self, errores: list[ErrorLLM]):
        self.errores = errores
        super().__init__(" | ".join(str(e) for e in errores))
